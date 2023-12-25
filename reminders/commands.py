import os

import reminders.whatsapp as wa
import reminders.chat as chat
import reminders.prompts_v2 as prompts
import reminders.utils as utils
import reminders.dynamodb as db

# this files handles all the commands that the user can send to Mindy
# /timezone, /reminders, /name, /feedback

def handler(msg, msg_id, timestamp, client, user, events, hist):
    tim = os.environ["TIM_PHONE_NUMBER"]
    commands = [
        "/timezone",
        "/reminders",
        "/reminder",
        "/name",
        "/feedback",
        "/verbose",
    ]
    command = None
    for c in commands:
        if msg.startswith(c):
            command = c
            break
    if not command:
        return False
    if command == "/verbose" and user.get("wa_id", "") != tim:
        return False
    
    hist.append({"role": "user", "content": msg, "timestamp": timestamp, "id": msg_id})
    
    if command == "/timezone":
        timezone_command(msg=msg, client=client, user=user, hist=hist)
    elif command == "/reminders" or command == "/reminder":
        reminders_command(events=events, client=client, user=user, hist=hist, timestamp=timestamp)
    elif command == "/name":
        name_command(msg=msg, client=client, user=user, hist=hist)
    elif command == "/feedback":
        feedback_command(wa_id=user["wa_id"], msg=msg, client=client, user=user, hist=hist)
    elif command == "/verbose":
        verbose_command(client=client, user=user)
    return True

def timezone_command(msg, client, user, hist):
    def send_timezone_error():
        wa.send(
            "Sorry, I couldn't update your timezone 😔, let's try again later", 
            user=user, 
            client=client, 
            hist=hist, 
            type_="timezone_update.error"
        )
        return

    if not msg.split("/timezone")[1].strip("`\"\' =:,"):
        # assume user just wants to know their timezone
        return wa.send(
            f"Your timezone is currently set to {user['user_timezone']}. To change it, just type /timezone <your new timezone>. 😊", 
            user=user, 
            client=client, 
            hist=hist, 
            type_="timezone_lookup.success"
        )
    out = chat.get_openai_completion(
        [
            {"role": "system", "content": prompts.UPDATE_TIMEZONE_PROMPT}, 
            {"role": "user", "content": msg}
        ]
    )
    if not out:
        print("0. OpenAI empty response")
        utils.log_msg(user, "OpenAI empty response.")
        send_timezone_error()
        return
    print(f"0. OpenAI response: {out}")

    tz = None
    for l in out.split('\n'):
        l = l.strip("`\"\' ")
        if l.startswith("timezone"):
            tz = l.split("timezone")[1].strip("`\"\' =:")
            break

    if not tz:
        # todo: could implement retry logic
        send_timezone_error()
        return
    
    if not utils.valid_timezone(tz):
        wa.send(
            "Mmh that doesn't look like a valid timezone or location... 🤔", 
            user=user, 
            client=client, 
            hist=hist, 
            type_="timezone_update.error"
        )
        return
    
    user["user_timezone"] = tz
    err = db.update_user_timezone(client=client, wa_id=user["wa_id"], timezone=tz)
    if err:
        send_timezone_error()
        return
    wa.send(
        f"Updated your timezone to: {tz}! 👍", 
        user=user, 
        client=client, 
        hist=hist, 
        type_="timezone_update.success"
    )
    return


def name_command(user, hist, client, msg):
    print(f"name command: {msg}")
    name = msg.split("=")[1].strip("\"\'`<>,. ")
    if not name:
        wa.send(
            "Sorry, I could not parse any name from your message 😔 Make sure to follow the format: /name=John", 
            user=user, 
            client=client,
            hist=hist, 
            type_="name_update.error"
        )
        return
    out = chat.get_openai_completion(
        [
            {"role": "system", "content": prompts.UPDATE_USERNAME_PROMPT}, 
            {"role": "user", "content": msg}
        ]
    )
    print(f"OpenAI response: {out}")
    if out.strip("`\"\' ").startswith("YES"):
        print("Flagged as offensive name.")
        wa.send(
            "Looks like this name is inappropriate 🙄 let's choose something else", 
            user=user, 
            client=client, 
            hist=hist, 
            type_="name_update.error"
        )
        return
    user["user_name"] = name
    err = db.update_user_name(client=client, wa_id=user["wa_id"], name=name)
    if err:
        wa.send(
            f"Sorry, I could not update your name to {name} 😔 Let's try again later.", 
            user=user, 
            client=client,
            hist=hist, 
            type_="name_update.error"
        )
        return 
    wa.send(
        f"Sounds good, I'll call you {name} from now on! 👍", 
        user=user, 
        client=client, 
        hist=hist, 
        type_="name_update.success"
    )
    return

def reminders_command(events, client, user, hist, timestamp):
    future_events = []
    for e in events:
        if e.get("version", "") != "2":
            continue
        from_date = int(e["from_date"])
        to_date = int(e["to_date"])
        if (from_date >= timestamp) or (to_date >= timestamp and to_date > 0):
            future_events.append(e)
    
    if not future_events:
        wa.send(
            "You have no upcoming reminders 🥲", 
            user=user, 
            client=client, 
            hist=hist
        )
        return
    reminders_str = "\n".join(f"- name:{v['event_name']}, time:{v['from_date_str']}, frequency: {v['frequency']}" for v in future_events)
    wa.send(
        f"Here are your upcoming reminders:\n{reminders_str}", 
        user=user, 
        client=client, 
        hist=hist
    )
    return

def feedback_command(wa_id, msg, client, user, hist):
    feedback_msg = msg.split("/feedback")[1].strip(":=;,`\"\'")
    err = db.insert_new_feedback(client, wa_id=user["wa_id"], feedback_msg=feedback_msg)
    if err:
        utils.log_msg(user, f"Error inserting feedback: {err}")
        wa.send(
            "Sorry I couldn't submit your feedback 😔 let's try again later.", 
            user=user, 
            client=client, 
            hist=hist, 
            type_="feedback.error"
        )
        return
    wa.send(
        "Thanks for your feedback! 🤩", 
        user=user, 
        client=client, 
        hist=hist, 
        type_="feedback.success"
    )
    return

def verbose_command(client, user):
    wa_id = user.get("wa_id", "")
    if wa_id != os.environ["TIM_PHONE_NUMBER"]:
        return
    verbose = not user.get("verbose", False)
    err = db.set_verbosity(client, wa_id, verbose)
    if err:
        wa.send_message(wa_id, f"Error setting verbosity. verbosity setting: {not verbose}")
        return
    wa.send_message(wa_id, f"Verbosity set to: {verbose}")
    return