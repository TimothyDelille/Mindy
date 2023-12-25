import reminders.whatsapp as wa
import reminders.dynamodb as db
from reminders.reschedule import future_dates_from_regex
from reminders.utils import log_msg

def execute(fn, kwargs, user, events, client):
    wa_id = user["wa_id"]
    verbose = user.get("verbose", False)
    if fn == "create":
        return create(
            client=client, 
            wa_id=wa_id, 
            event_name=kwargs["event_name"], 
            from_date=kwargs["from_date"], 
            from_date_str=kwargs["from_date_str"], 
            to_date=kwargs["to_date"], 
            to_date_str=kwargs["to_date_str"], 
            frequency=kwargs["frequency"],
            stats=user["stats"],
            verbose=verbose,
        )
    elif fn == "update":
        return update(
            client=client, 
            wa_id=wa_id,
            events=events, 
            stats=user["stats"],
            from_date=kwargs["from_date"],
            from_date_str=kwargs["from_date_str"],
            to_date=kwargs["to_date"],
            to_date_str=kwargs["to_date_str"],
            frequency=kwargs["frequency"],
            event_index=kwargs["event_index"],
            event_name=kwargs["event_name"],
            verbose=verbose,
        )
    elif fn == "delete":
        event, err = db.get_event_from_index(event_index=kwargs["event_index"], events=events)
        if err:
            log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not get event from index: {err}")
            return err
        
        log_msg(wa_id=wa_id, verbose=verbose, msg=f"Got following event from index: {event['event_name']}, ({event['from_date_str']})")
        err1 = db.delete_event(client, wa_id=wa_id, ts_bucket=event["ts_bucket"], event_id=event["event_id"])
        if err1:
            log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not delete event: {err1}. Event: {event}")
            return err1
        new_events = []
        for e in events:
            if e["event_id"] != event.get("event_id", ""):
                new_events.append(e)
        err2 = db.set_user_events_v2(client, wa_id, new_events)
        if err2:
            log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not set user events: {err2}")
        else:
            new_events_str =  ", ".join(f"{e['event_name']}, ({e['from_date_str']})" for e in new_events)
            log_msg(wa_id=wa_id, verbose=verbose, msg=f"Successfully set user events to {new_events_str}")
        err_stats = db.set_user_stats(client=client, wa_id=wa_id, stats=user["stats"], message_inc=0, reminder_inc=-1)
        return None
    elif fn == "update_timezone":
        return update_timezone(client=client, wa_id=wa_id, timezone=kwargs["timezone"])
    else:
        print(f"execute. Uknown function {fn} with arguments {kwargs}")
    return None

def create(client, wa_id, event_name, from_date, from_date_str, to_date, to_date_str, frequency, stats, verbose=False):
    future_dates, err = future_dates_from_regex(
        frequency=frequency, 
        from_date_ts=from_date,
        to_date_ts=to_date,
    )

    event_id = db.get_event_id_v2(
        wa_id=wa_id, 
        event_name=event_name, 
        from_date=from_date, 
        to_date=to_date, 
        frequency=frequency
    )

    ts_bucket = db.get_ts_bucket(from_date)

    children = []
    err = "DUMMY_ERR"
    if not err and future_dates:
        for child_date_ts in future_dates:
            child_event_id = db.get_event_id_v2(
                wa_id=wa_id,
                event_name=event_name,
                from_date=child_date_ts,
                to_date=-1,
                frequency="once",
            )
            child_ts_bucket = db.get_ts_bucket(child_date_ts)
            
            child_err = db.create_event_v2(
                client=client,
                wa_id=wa_id,
                ts_bucket=child_ts_bucket,
                event_id=child_event_id,
                event_name=event_name,
                from_date=child_date_ts,
                from_date_str=from_date_str,
                to_date=to_date,
                to_date_str=to_date_str,
                frequency=frequency,
                reschedule=False,
            )

            if child_err:
                continue

            children.append({
                "ts_bucket": child_date_ts,
                "event_id": child_event_id,
            })
    else:
        err_create = db.create_event_v2(
            client=client,
            wa_id=wa_id,
            ts_bucket=ts_bucket,
            event_id=event_id,
            event_name=event_name,
            from_date=from_date,
            from_date_str=from_date_str,
            to_date=to_date,
            to_date_str=to_date_str,
            frequency=frequency,
            reschedule=True,
        )

        if err_create:
            err_msg = f"Could not create event: {err_create}"
            log_msg(wa_id=wa_id, verbose=verbose, msg=err_msg)
            return err_msg
    
    tim_msg_list = []
    if children:
        tim_msg_list.append(f"Created {len(children)} children events.")

    err_update = db.update_user_events_v2(
        client=client, 
        wa_id=wa_id, 
        events=[
            { 
                "event_id": event_id,
                "event_name": event_name,
                "from_date": from_date,
                "from_date_str": from_date_str,
                "to_date": to_date,
                "to_date_str": to_date_str,
                "frequency": frequency,
                "children": children,
                "ts_bucket": ts_bucket,  # legacy
            }
        ]
    )  # err_update not critical

    if err_update:
        log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not update user events. Error: {err_update}")
    else:
        log_msg(wa_id=wa_id, verbose=verbose, msg="Updated user events.")

    err_stats = db.set_user_stats(client=client, wa_id=wa_id, stats=stats, message_inc=0, reminder_inc=1)
    if err_stats:
        log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not update user stats. Error: {err_stats}")
    else:
        log_msg(wa_id=wa_id, verbose=verbose, msg="Updated user stats.")

    return None

def update(client, wa_id, from_date, from_date_str, to_date, to_date_str, frequency, event_name, event_index, events, stats, verbose=False):
    ts_bucket = db.get_ts_bucket(from_date)
    event_id = db.get_event_id_v2(
        wa_id=wa_id,
        event_name=event_name,
        from_date=from_date,
        to_date=to_date,
        frequency=frequency,
    )
    event, err = db.get_event_from_index(event_index=event_index, events=events)
    if err:
        log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not get event from index: {err}. Falling back to `create`")
        # fallback to `create`
        return create(
            client=client, 
            wa_id=wa_id, 
            event_name=event_name, 
            from_date=from_date, 
            from_date_str=from_date_str, 
            to_date=to_date, 
            to_date_str=to_date_str, 
            frequency=frequency,
            stats=stats,
            verbose=verbose,
        )
    
    log_msg(wa_id=wa_id, verbose=verbose, msg=f"Extracted event using index: {event}.")
    err1 = db.delete_event(client=client, wa_id=wa_id, ts_bucket=event["ts_bucket"], event_id=event["event_id"])
    if err1:
        log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not delete event: {err1}. Event: {event}")
    err2 = db.create_event_v2(
        client=client,
        wa_id=wa_id,
        ts_bucket=ts_bucket,
        event_id=event_id,
        event_name=event_name,
        from_date=from_date,
        from_date_str=from_date_str,
        to_date=to_date,
        to_date_str=to_date_str,
        frequency=frequency,
    )

    if err2:
        log_msg(wa_id=wa_id, verbose=verbose, msg=f"Could not update event: {err2}.")
        return err2
    
    err3 = db.update_user_events(client, wa_id, [{"ts_bucket": ts_bucket, "event_id": event_id}])
    return None

def update_timezone(client, wa_id, timezone):
   err = db.update_user_timezone(client=client, wa_id=wa_id, timezone=timezone)
   return err
