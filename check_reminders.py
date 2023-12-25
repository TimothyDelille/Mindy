import time

import reminders.dynamodb as db
import reminders.reschedule as reschedule
import reminders.utils as utils
import reminders.whatsapp as wa


DUMMY_WA_ID = "test"

# TODO:
# programmatically update event bridge rule with earliest
# reminder time instead of checking every 5 minutes
def check_reminders():
    client = db.get_client()
    events, err = db.get_upcoming_events(client)

    if err:
        print(f"get_upcoming_events error: {err}")
        return

    if not events:
        return
    
    # sort events by ascending reminder time.
    events = sorted(events, key=lambda e: int(e["from_date"]))
    for event in events:
        # ignore test events.
        if event["wa_id"] == DUMMY_WA_ID:
            continue
        # update `scheduled` status to True
        db.mark_event_as_scheduled(client, event["ts_bucket"], event["event_id"])
        # schedule new event if this is a recurrent event
        err_msg = reschedule.reschedule_reminder_v2(client, event)
        if err_msg:
            utils.log_msg({"wa_id": event["wa_id"], "verbose": True}, err_msg)
        curr_ts = int(event["from_date"])
        t = max(0, curr_ts - utils.utc_now_ts())
        time.sleep(t)
        text = event["event_name"]
        frequency = event["frequency"]
        if frequency != "once":
            if err_msg:
                text += "\n" + err_msg
            else:
                text += f" ({frequency})"

        wa.send_reminder_en(event["wa_id"], text)
        template = f"Reminder!😊 \n{text}\nLet me know if you need anything else."
        new_msg = [
            {
                "text": template,
                "role": "assistant",
                "timestamp": utils.utc_now_ts(),
                "setup": "false",
                "type": "reminder",
                "version": "2",
            }
        ]
        db.update_user_conversation(client, event["wa_id"], new_msg)