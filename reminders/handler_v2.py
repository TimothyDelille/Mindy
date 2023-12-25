import reminders.chat as chat
import reminders.prompts_v2 as prompts
import reminders.utils as utils
import reminders.parser as parser
import reminders.dynamodb as db
import reminders.whatsapp as wa
import reminders.execute as execute
import reminders.commands as commands

import logging

logging.basicConfig(level = logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# on local:
# console_handler = logging.StreamHandler()
# console_handler.setLevel(logging.DEBUG)
# logger.addHandler(console_handler)

FAILURE_MESSAGE = "Sorry there was an error 😔 let's try again later"

# takes user dict and turn past conversation into OpenAI ingestable messages.
# we start with prompt and only include the last X messages.
def construct_hist_from_conversation(user):
    # conversation = [{"text": <string>, "timestamp": <int (ms)>, "role": <string: user or assistant>}]
    conv_len = len(user["conversation"])
    prompt = prompts.MINDY_PROMPT
    prompt += f"\n\nThe user's name is {user['user_name']}, and their timezone is set to {user['user_timezone']}"
    hist = [{"role": "system", "content": prompt, "exclude": True}]

    start = max(conv_len - 20, 0)  # include the last 10 user messages: not exactly cause mindy logs multiple messages per request.
    for i in range(start, conv_len):
        msg = user["conversation"][i]
        if msg.get("version", "") != "2" or int(msg["timestamp"]) < utils.utc_now_ts() - 48*60*60:
            continue
        # exclude (bool) determines whether to exclude a message from the dynamodb conversation update.
        hist.append({"role": msg["role"], "content": msg["text"], "type": msg.get("type", ""), "exclude": True})

        if i - start % 4 == 0 and i > start:
            hist.append({"role": "user", "content": prompts.MINDY_REPEAT_PROMPT, "exclude": True})
    return hist

def run(msg, msg_id, user, timestamp, events, client):
    logger.debug(f"User says: {msg}")
    # msg: comes from user
    hist = construct_hist_from_conversation(user)

    # 0. handle user commands /timezone, /name, /reminders and /feedback
    ok = commands.handler(
        msg=msg, 
        msg_id=msg_id, 
        timestamp=timestamp, 
        client=client, 
        user=user, 
        events=events,
        hist=hist
    )
    if ok:
        return

    # 1. Fetch response from Mindy
    now = utils.utc_to_usr_local_str(timestamp, tz=user["user_timezone"])
    user_message_formatted = (
        f"{msg}\n"
        f"# Sent on: {now}\n"
    )
    hist.append({"role": "user", "content": user_message_formatted, "timestamp": timestamp, "id": msg_id})
    filtered_types = ["command"]  # not filter out `request`type? `command` is the command that programming mindy writes, not a user command like /reminders.
    out_1 = chat.get_openai_completion(
        [
            {"role": m["role"], "content": m["content"]} \
            for m in hist if m.get("type", "") not in filtered_types
        ]
    )
    if not out_1:
        utils.log_msg(user, "OpenAI empty response.")
        wa.send(FAILURE_MESSAGE, user=user, client=client, hist=hist, type_="error")
        return

    logger.debug(f"1. Mindy responds: {out_1}")

    # safeguard agains hallucinations
    out_1 = hallucinations_safeguard(user=user, out=out_1, hist=hist)
            
    # 2. @manager in response?
    if "@manager" not in out_1.lower():
        return chat_response(msg=msg, out=out_1, user=user, client=client, hist=hist)

    logger.debug("@manager in response.")
    # 4. Give programming commands to Mindy
    formatted_request = "@manager: " + out_1.split("@manager")[1].strip(":, ")
    hist.append({"role": "assistant", "content": formatted_request, "type": "request", "timestamp": utils.utc_now_ts()})

    programming_msg = prompts.MINDY_PROGRAMMING_PROMPT
    future_events = []
    for e in events:
        if e.get("version", "") != "2":
            continue
        from_date = int(e["from_date"])
        to_date = int(e["to_date"])
        if (from_date >= timestamp) or (to_date >= timestamp and to_date > 0):
            future_events.append(e)

    reminders_str = ""
    if future_events:
        reminders_str = "\n".join(f"- id:{k}, name:{v['event_name']}, from_date:{v['from_date_str']}, to_date:{v['to_date_str']}, frequency: {v['frequency']}" for k, v in enumerate(future_events))
        programming_msg += f"\n\nIf you need to update or delete a reminder, here are {user['user_name']}'s upcoming reminders:\n{reminders_str}"
    programming_msg += f"\n\nWrite the commands to fulfill the request below:\n{formatted_request}"

    programming_hist = [{"role": m["role"], "content": m["content"]} for m in hist] + [{"role": "user", "content": programming_msg}]
    out_4 = chat.get_openai_completion(programming_hist)

    utils.log_msg(user, f"Manager request: {formatted_request}.\nReminders: {reminders_str}\nResponse: {out_4}")
    if not out_4:
        utils.log_msg(user, "OpenAI empty response.")
        return wa.send(FAILURE_MESSAGE, user=user, client=client, hist=hist, type_="error")
    logger.debug(f"Programming answer: {out_4}")

    # 5. Extract parameters from the programming answer.
    params, err = parser.run(out_4, user)

    if err or not params:
        if not params and not err:
            err = "Could not extract any command from last message."
        utils.log_msg(user, f"extract_params 1: {err}. Retry.")
        programming_hist.append({"role": "assistant", "content": out_4})

        retry_msg = f"@manager:\nThe commands you generated resulted in the following error: {err}. Please write a corrected version of the commands you sent."
        programming_hist.append({"role": "user", "content": retry_msg})

        out_4 = chat.get_openai_completion(programming_hist)
        if not out_4:
            utils.log_msg(user, "OpenAI empty response.")
            return wa.send(FAILURE_MESSAGE, user=user, client=client, hist=hist, type_="error")
        logger.debug(f"5. Mindy says: {out_4}")
        params, err = parser.run(out_4, user)

        utils.log_msg(user, f"Extracted params: {params}")
        if err or not params:
            if not params and not err:
                err = "params is empty"
            utils.log_msg(user, f"extract_params error after 2nd try: {err}")
            return wa.send(FAILURE_MESSAGE, user=user, client=client, hist=hist, type_="error")

    logger.debug(f"5. Extracted params: {params}")
    # we add it to the history to give it back to programming mindy. Otherwise she will create reminders that were already created before.
    hist.append({"role": "assistant", "content": out_4, "type": "command", "timestamp": utils.utc_now_ts()})

    # 7. Execute commands
    for fn, kwargs in params:
        if fn == "fetch":
            if future_events:
                reminders_str = "\n".join(f"- name:{v['event_name']}, time:{v['from_date_str']}, frequency: {v['frequency']}" for v in future_events)
                fetch_resp = f"Here are your upcoming reminders:\n{reminders_str}\n\nYou can also type /reminders to access your future reminders."
            else:
                fetch_resp = "You have no upcoming reminders 🥲\nIn the future, you can also type /reminders to access your reminders."
            return wa.send(fetch_resp, user=user, client=client, hist=hist)

        err = execute.execute(fn, kwargs, user, future_events, client)
        if not err:
            continue
        # handle error.
        # todo: make it more interpretable? Maybe not all commands failed. Can result in surprising results for the user.
        utils.log_msg(user, f"execution error: {err}")
        return wa.send(FAILURE_MESSAGE, user=user, client=client, hist=hist, type_="error")

    # 8. send confirmation message.
    # also all my reminders got canceled due to retry :((
    out_8 = chat.get_openai_completion([
        {"role": m["role"], "content": m["content"]} for m in hist if m.get("type", "") != "command"] +\
        [{"role": "user", "content": prompts.CONFIRMATION_PROMPT}]
    )

    if (not out_8) or ("@user" not in out_8.lower()): # fallback to boilerplate message
        logger.debug("8. Empty confirmation. Return boilerplate message.")
        return wa.send("Done! 😊", user=user, client=client, hist=hist)
    logger.debug(f"8. Confirmation message: {out_8}")
    confirmation_message = out_8.split("@user")[-1].strip(",: ")
    return wa.send(confirmation_message, user=user, client=client, hist=hist)

def hallucinations_safeguard(user, out, hist):
    hallucinations = [
        "i'll set up",
        "i just set a reminder",
        "i will remind you to",
        "i'll remind you to",
        "i'll set a reminder",
        "i will set a reminder",
        "i'll set up a reminder",
        "i will set up a reminder",
        "i'll create a reminder",
        "i will create a reminder",
        "all set",
        "reminder set",
        "done!",
        "i've just scheduled a reminder",
        "i have just scheduled a reminder",
        "i scheduled a reminder",
        "i've just set a reminder",
        "i have just set a reminder",
        "i set a reminder",
        "i've just created a reminder",
        "i have just created a reminder",
        "i created a reminder",        
    ]

    out_lower = out.lower()
    if ("@manager" in out_lower) or not any(h in out_lower for h in hallucinations):
        return out
    
    utils.log_msg(user, f"Hallucination: {out}")
    filtered_types = ["command", "reminder"]
    clean_hist = [{"role": m["role"], "content": m["content"]} for m in hist if m.get("type", "") not in filtered_types]
    out_new = chat.get_openai_completion(
        clean_hist +\
        [
            {"role": "assistant", "content": out},
            {"role": "user", "content": "Looks like you sent a confirmation, please rewrite this as a request to @manager. If you don't have all the information yet, just go on with the conversation."},
        ]
    )
    utils.log_msg(user, f"Hallucination, 2nd response: {out_new}")
    if "@manager" in out_new.lower():
        return out_new
    return out

def check_is_about_timezone(msg):
    msg_lower = msg.lower()
    return ("timezone" in msg_lower) or ("time zone" in msg_lower)

def chat_response(msg, out, user, client, hist):
    # Is it about a timezone or username change? (can do in parallel)
    # not run if @manager is in the response.
    # out_new = chat.get_openai_completion(
    #     [
    #         {"role": "system", "content": prompts.SETTINGS_PROMPT},
    #         {"role": "user", "content": msg},
    #     ]
    # )

    # if not out_new:
    #     wa.send(out, user=user, client=client, hist=hist)
    #     return
    
    # print(f"timezone or username change? {out_new}")

    # def check(l, key):
    #     return l.startswith(key) and l.split(key)[1].strip(":`\"' ") == "yes"
    
    # for l in out_new.split("\n"):
    #     l = l.lower()
    #     l = l.strip("`\"\' ")

    #     if check(l, "timezone"):
    #         out += "\nTo update your timezone, use the command: /timezone=your new timezone or location."
    #         logger.debug("setting timezone to True")
    #     # elif check(l, "username"):
    #     #     out += "\nTo update your name, user the command: /name=John (for example)."
    #     #     logger.debug("setting username to True")

    if check_is_about_timezone(msg):
        out += "\nTo update your timezone, use the command: /timezone=your new timezone or location."
        logger.debug("msg is about timezone.")

    wa.send(out, user=user, client=client, hist=hist)
    return