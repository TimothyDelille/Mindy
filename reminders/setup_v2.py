import reminders.prompts_v2 as prompts
import reminders.chat as chat
import reminders.dynamodb as db
import reminders.whatsapp as wa
import reminders.utils as utils

import logging

logging.basicConfig(level = logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# todo: haven't looked at this in a while. time to update probably.
def run(msg, user, timestamp, client):
    # user = {
    # "wa_id": string,
    # "name": string,
    # "timezone": string,
    # "conversation": list
    # }
    conversation = user["conversation"]
    conv_len = len(conversation)
    hist = [{"role": "system", "content": prompts.SETUP_PROMPT, "exclude": True}]
    for i in range(max(conv_len - 8, 0), conv_len):  # include the last 4 user messages
        m = user["conversation"][i]
        if m.get("type", "") != "setup":
            continue
        # exclude (bool) determines whether to exclude a message
        # from the dynamodb conversation update.
        hist.append({"role": m["role"], "content": m["text"], "type": m.get("type", ""), "exclude": True})

    hist.append({"role": "user", "content": msg, "type": "setup", "timestamp": timestamp})
    out = chat.get_openai_completion([{"role": msg["role"], "content": msg["content"]} for msg in hist])

    if not out:
        return wa.send("Sorry there was an error 😔 let's try again later", user=user, client=client, hist=hist, type_="error")
    if "---" not in out:
        return wa.send(out, user=user, client=client, hist=hist, type_="setup")

    for line in out.split('---')[1].split('\n'):
        line = line.strip("`\"\', ")
        if not line:
            continue
        k, v = line.split(":")
        v = v.strip("`\"\', ")
        if k == "name":
            if not v:
                # todo: fire failure metric
                return wa.send("Sorry, I could not parse any name from your message 😔", user=user, client=client, hist=hist, type_="setup_name.error")
            err = db.update_user_name(client=client, wa_id=user["wa_id"], name=v)
            if err:
                return wa.send("Sorry, I could not update your name 😔 Can you repeat please?", user=user, client=client, hist=hist, type_="setup_name.error")
            user["user_name"] = v
        elif k == "timezone":
            if not utils.valid_timezone(v):
                return wa.send("Mmh that doesn't look like a valid timezone or location... 🤔", user=user, client=client, hist=hist, type_="setup_timezone.error")
            err = db.update_user_timezone(client=client, wa_id=user["wa_id"], timezone=v)
            if err:
                return wa.send("Sorry, I could not update your timezone 😔 Can you repeat please?", user=user, client=client, hist=hist, type_="setup_timezone.error")
            user["user_timezone"] = v

    # if username or timezone is missing, continue conversation.
    # should not happen, usually Mindy returns both at once.
    if not user["user_name"] or not user["user_timezone"]:
        out = out.split("---")[0]  # remove command from the response
        return wa.send(out, user=user, client=client, hist=hist)
    return wa.send(prompts.INTRO_MESSAGE.format(name=user["user_name"]), user=user, client=client, hist=hist, type_="setup_done")
