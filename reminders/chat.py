import os
import datetime
import requests
import logging

import reminders.prompts as prompts
import reminders.utils as utils


logging.basicConfig(level = logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def get_openai_completion(messages):
    timeout = 10
    retries = 5
    headers = {"Content-Type": "application/json", "Authorization": "Bearer %s" % os.environ["OPENAI_KEY"]}
    data = {"model": "gpt-3.5-turbo", "messages": messages, "temperature": 0, "max_tokens": 500}
    req_counter = 0
    timed_out = False
    while req_counter == 0 or (timed_out and req_counter < retries):
        try:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=timeout)
            timed_out = False
            result = response.json()
        except requests.exceptions.Timeout:
            logger.debug(f"make_completion_request: retry after timeout={timeout}. attempt: {req_counter}")
            timed_out = True
            result = dict()
        req_counter += 1

    try:
        out_msg = result['choices'][0]['message']['content']
    except Exception as e:
        out_msg = ""
        # logger.debug(f"get_openai_completion. Error: {e}. Response: {result}")
    return out_msg

# todo: retry when params are wrong
# todo: still log usr_msg if chat doesn't work
# todo: delete command doesn't work, gpt seems to forget prompt
def run(user: dict, usr_msg: str, timestamp: int, events: list):
    conversation = user["conversation"] # conversation = [{"text": <string>, "timestamp": <int (ms)>, "role": <string: user or assistant>}]

    utcnow = int(datetime.datetime.utcnow().timestamp())
    messages = [{"role": "system", "content": prompts.SYSTEM_PROMPT_V2}]
    messages.extend([{"role": msg["role"], "content": msg["text"]} for msg in conversation if int(msg["timestamp"]) >= utcnow - 48*60*60])

    timezone = user["user_timezone"]
    now = utils.utc_to_usr_local_str(timestamp, timezone)

    future_events = []
    past_events = []
    for i, e in enumerate(events): # events should be sorted in ascending order already
        time = utils.utc_to_usr_local_str(int(e["event_timestamp"]), timezone)
        if int(e["event_timestamp"]) >= timestamp:
            future_events.append(f"# id:{i}, name:{e['event_name']}, time:{time}, frequency:{e['frequency']}")
        else:
            past_events.append(f"# id:{i}, name:{e['event_name']}, time:{time}, frequency:{e['frequency']}")

    past_events_prompt = 'None' if not past_events else '\n'.join("- " + e for e in past_events)
    future_events_prompt = 'None' if not future_events else '\n'.join("- " + e for e in future_events)
    usr_msg_fmted = (
        f"{usr_msg}\n\n"
        "# METADATA\n"
        f"# Current time: {now}\n"
        f"# Timezone: {user['user_timezone']}\n"
        f"# Name: {user['user_name']}\n"
        "# Upcoming reminders:\n"
        f"{future_events_prompt}\n"
    )
    print(usr_msg_fmted)
    messages.append({"role": "user", "content": usr_msg_fmted})
    if len(conversation) % 4 == 0 and len(conversation) > 0:
        messages.append({"role": "system", "content": prompts.REMINDER_PROMPT})
    return get_openai_completion(messages)

# TODO: clean this up lol.
def reschedule_event(event):
    system_prompt = (
    f"Current datetime is {event['event_timestamp_str']}, a reminder is going off and its frequency is: {event['frequency']}. Has a stopping condition been met? If not, when is the next time that this reminder will go off?\n"
    f"Give your answer as a datetime in the format {utils.TIME_FORMAT} and fill out the following template:\n"
    "ANSWER=<your answer>\n"
    "Return ANSWER=None if the reminder is not supposed to be rescheduled\n\n"

    "Some examples:\n"
    "Current datetime: Monday, 2023-04-10 13:30:00. Frequency: Every hour until 2pm\n"
    "ANSWER=None\n"
    "Explanation: the reminder is supposed to stop at 2pm. If we reschedule it for 14:30:00 we would have violated the stopping condition.\n\n"

    "Current datetime: Thursday, 2023-04-06 09:00:00. Frequency: Every day except on week-ends.\n"
    "ANSWER=Friday, 2023-04-07 09:00:00\n\n"

    "Current datetime: Friday, 2023-04-07 09:00:00. Frequency: Every day except on week-ends.\n"
    "ANSWER=None\n\n"
    )
    system_prompt_1 = (
        "Your job is to send reminders to a user."
        f"A reminder is scheduled on {event['event_timestamp_str']}."
        f"Moreoever, the user wants you to remind them of this at the following frequency: {event['frequency']}."
        f"When should the next reminder be sent? Give your answer in the format {utils.TIME_FORMAT} and fill out the following template:\n"
        "ANSWER=<your answer> (set to none if the reminder should not be scheduled again)\n"
        "Don't include any comments."
    )
    system_prompt_2 = (
        "Your job is to send reminders to a user."
        f"A reminder is scheduled on {event['event_timestamp_str']}."
        f"Moreoever, the user wants you to remind them of this at the following frequency: {event['frequency']}."
        f"Independently of currently scheduled time, what was the stopping time implied by the frequency? Give your answer in the format {utils.TIME_FORMAT} and fill out the following template:\n"
        "ANSWER=<your answer> (set to none if no stopping time was set)"
    )

    msg_next_date = get_openai_completion(messages=[{"role": "system", "content": system_prompt_1}])
    msg_last_date = get_openai_completion(messages=[{"role": "system", "content": system_prompt_2}])

    def extract_date(msg):
        date = ""
        try:
            for line in msg.split("\n"):
                if not line.startswith("ANSWER"):
                    continue
                date = line.split("=")[1]
        except Exception as e:
            print(f"reschedule_event wrong format. {e}")
        return date

    next_date = extract_date(msg_next_date)
    last_date = extract_date(msg_last_date)
    return {"next_date": next_date, "last_date": last_date}

# todo: haven't looked at this in a while. time to update probably.
def setup_new_user(user: dict, usr_msg: str):
    # user = {"wa_id": string, "name": string, "language": string, "timezone": string, "conversation": list}
    print("Setting up new user: ", user)
    conversation = user["conversation"]

    messages = [{"role": "system", "content": prompts.SETUP_PROMPT}]
    messages.extend([{"role": msg["role"], "content": msg["text"]} for msg in conversation])
    messages.append({"role": "user", "content": usr_msg})

    out_msg = ""
    try:
        out_msg = get_openai_completion(messages)
        print(f"setup_new_user: out_msg={out_msg}")
    except Exception as e:
        print(f"setup_new_user. Error: {e}")

    return out_msg

