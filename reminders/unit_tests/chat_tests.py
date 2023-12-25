import os
import sys
reminders_dir = "/Users/timothydelille/mindy/"
sys.path.append(reminders_dir)

import reminders.chat as chat

def init_env_variables():
    with open(".env", 'r') as f:
        env_vars = f.readlines()
    for k, v in map(lambda x: x.strip("\n").split('='), env_vars):
        os.environ[k] = v

def test_reschedule_reminder():
    tests = [
        {
            "event_name": "call mom",
            "event_timestamp_str": "Thursday, 2023-04-06 18:00:00",
            "frequency": "once",
            "expected": {"next_date": "none", "last_date": "none"}
        },
        {
            "event_name": "do laundry",
            "frequency": "every hour until 4 pm",
            "event_timestamp_str": "Saturday, 2023-04-08 13:50:00",
            "expected": {"next_date": "Saturday, 2023-04-08 14:50:00", "last_date": "Saturday, 2023-04-08 16:00:00"}
        },
        {
            "event_name": "do laundry",
            "frequency": "every hour until 4 pm",
            "event_timestamp_str": "Saturday, 2023-04-08 15:50:00",
            "expected": {"next_date": "none", "last_date": "Saturday, 2023-04-08 16:00:00"}
        },
        {
            "event_name": "do laundry",
            "frequency": "every hour until 4 pm",
            "event_timestamp_str": "Saturday, 2023-04-08 18:30:00",
            "expected": {"next_date": "none", "last_date": "Saturday, 2023-04-08 16:00:00"}
        },
        {
            "event_name": "university assignment",
            "frequency": "every hour until I do it",
            "event_timestamp_str": "Saturday, 2023-04-08 18:30:00",
            "expected": {"next_date": "Saturday, 2023-04-08 19:30:00", "last_date": "none"}
        }
    ]

    passed = True
    for i, t in enumerate(tests):
        event = {
            "event_name": t["event_name"],
            "event_timestamp_str": t["event_timestamp_str"],
            "frequency": t["frequency"],
        }
        out = chat.reschedule_event(event=event)

        if out["next_date"] != t["expected"]["next_date"]:
            passed = False
            print(f"Test {i} failed. Expected: next_date={t['expected']['next_date']}, got: next_date={out['next_date']}")

        if out["last_date"] != t["expected"]["last_date"]:
            passed = False
            print(f"Test {i} failed. Expected: last_date={t['expected']['last_date']}, got: last_date={out['last_date']}")
    if passed:
        print("PASSED")

if __name__ == "__main__":
    init_env_variables() # needed to call OpenAI.
    print("Test chat.reschedule_reminder...")
    test_reschedule_reminder()
