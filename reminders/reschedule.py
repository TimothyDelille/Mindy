import re
import datetime

import reminders.chat as chat
import reminders.dynamodb as db
import reminders.prompts_v2 as prompts_v2
import reminders.utils as utils

# writes new reminder to dynamodb and returns an error message to be sent to the user.
def reschedule_reminder_v2(client, event):
    if not event.get("reschedule", True):
        return
    
    wa_id = event["wa_id"]
    user, err = db.get_user(client, wa_id)
    if err or not user.get("user_timezone"):
        tz = "UTC"
    else:
        tz = user["user_timezone"]

    frequency = event["frequency"].lower().strip()
    curr_ts = int(event["from_date"])

    if frequency == "once":
        return

    # todo: this parsing could be done right after setting the event.
    next_ts, err = next_timestamp_from_regex(frequency, curr_ts)

    if err or next_ts == -1:
        if err == "too_frequent":
            return "This reminder won't get rescheduled because it has a frequency below 5 minutes."

        next_ts, err = next_timestamp_from_language_model(frequency, curr_ts, tz)
        if err or next_ts == -1:
            return


    if int(event["to_date"]) > 0 and next_ts > int(event["to_date"]):  # why > 0 check? to_date is set to -1 if it's a recurring event with no end date.
        return

    ts_bucket = db.get_ts_bucket(next_ts)

    event_id = db.get_event_id_v2(
        wa_id=event["wa_id"],
        event_name=event["event_name"],
        from_date=next_ts,
        to_date=event["to_date"],
        frequency=event["frequency"],
    )

    err = db.create_event_v2(
        client=client,
        wa_id=wa_id,
        event_id=event_id,
        ts_bucket=ts_bucket,
        event_name=event["event_name"],
        from_date=next_ts,
        from_date_str = utils.utc_to_usr_local_str(next_ts, tz=tz),
        to_date=event["to_date"],
        to_date_str=event["to_date_str"],
        frequency=event["frequency"],
    )
    if err:
        return "I ran into an issue while trying to reschedule this reminder..."
    _ = db.update_user_events(client, wa_id, [{"ts_bucket": ts_bucket, "event_id": event_id}])

# returns next date as a timestamp, error
def next_timestamp_from_language_model(frequency, from_date, tz):
    from_date = utils.utc_to_usr_local_str(from_date, tz)

    msg = prompts_v2.GET_NEXT_DATE.format(date=from_date, frequency=frequency, time_format=utils.TIME_FORMAT)
    out = chat.get_openai_completion([{"role": "system", "content": msg}])

    if not out:
        return -1, "empty OpenAI response"

    next_date = ""
    for line in out.split("\n"):
        if not line.startswith("ANSWER") and "=" not in line:
            continue
        next_date = line.split("=")[1]

    if not next_date:
        return -1, f"could not extract date from output: {out}"

    try:
        next_date_ts = utils.usr_local_str_to_utc(next_date, tz)
        return next_date_ts, None
    except Exception as _:
        return -1, f"could not parse date: {next_date}"

def get_future_dates_from_regex(frequency, from_date_ts, to_date_ts):
    curr_ts = from_date_ts
    next_ts = -1
    future_ts = []
    # todo: can this grow out of hand?
    while next_ts < to_date_ts:
        next_ts, err = next_timestamp_from_regex(frequency=frequency, from_date_ts=from_date_ts)
        if err:
            return [], err
        future_ts.append(next_ts)
    return future_ts, None

# return next date as a timestamp, error
def next_timestamp_from_regex(frequency, from_date_ts):
    future_dates, error = future_dates_from_regex(frequency, from_date_ts=from_date_ts, to_date_ts=-1)

    if error or not future_dates:
        return -1, error

    next_date_ts = future_dates[0]
    return next_date_ts, None

# future_dates_from_regex returns a list of future dates as timestamps.
# if to_date_ts == -1, it just returns the next date (wrapped in a list).
def future_dates_from_regex(frequency, from_date_ts, to_date_ts=-1):
    m = re.match(r'^every\s?(\d*)\s(minutes?|hours?|days?|weeks?|months?|years?)$', frequency)

    if not m:
        return None, f"could not parse frequency: {frequency}"

    value_, unit = m.groups()
    value = 1
    if value_:
        try:
            value = int(value_)
        except Exception as _:
            return None, f"could not parse value: {value_}"

    if value < 5 and unit == "minutes":
        return None, "too_frequent"
    
    from_date = utils.from_timestamp(from_date_ts, "UTC")
    to_date = utils.from_timestamp(to_date_ts, "UTC")
    
    if (unit == "minutes") or (unit == "minute"):
        delta = datetime.timedelta(minutes=value)
        if to_date_ts == -1:
            next_date = from_date + delta
            return [int(next_date.timestamp())], None
        intervals = (to_date_ts - from_date_ts) // (value * 60)
        all_dates = [from_date + i*delta for i in range(1, intervals)]
        # convert to timestamps
        return [int(d.timestamp()) for d in all_dates], None
    elif (unit == "hours") or (unit == "hour"):
        delta = datetime.timedelta(hours=value)
        if to_date_ts == -1:
            next_date = from_date + delta
            return [int(next_date.timestamp())], None
        intervals = (to_date_ts - from_date_ts) // (value * 60 * 60)
        all_dates = [from_date + i*delta for i in range(1, intervals)]
        return [int(d.timestamp()) for d in all_dates], None
    elif (unit == "days") or (unit == "day"):
        delta = datetime.timedelta(days=value)
        if to_date_ts == -1:
            next_date = from_date + delta
            return [int(next_date.timestamp())], None
        intervals = (to_date_ts - from_date_ts) // (value * 60 * 60 * 24)
        all_dates = [from_date + i*delta for i in range(1, intervals)]
        return [int(d.timestamp()) for d in all_dates], None
    elif (unit == "weeks") or (unit == "week"):
        delta = datetime.timedelta(weeks=value)
        if to_date_ts == -1:
            next_date = from_date + delta
            return [int(next_date.timestamp())], None
        intervals = (to_date_ts - from_date_ts) // (value * 60 * 60 * 24 * 7)
        all_dates = [from_date + i*delta for i in range(1, intervals)]
        return [int(d.timestamp()) for d in all_dates], None
    elif (unit == "months") or (unit == "month"):
        # here we have to replace the month value because not all months have the same number 
        # of days.
        if to_date_ts == -1:
            next_date = from_date.replace(month=(from_date.month + value - 1)%12 + 1)
            return [int(next_date.timestamp())], None
        all_dates = []
        next_date = from_date
        while next_date < to_date:
            next_date = next_date.replace(month=(next_date.month + value - 1)%12 + 1)
            all_dates.append(next_date)
        return [int(d.timestamp()) for d in all_dates], None
    elif (unit == "years") or (unit == "year"):
        if to_date_ts == -1:
            next_date = from_date.replace(year=from_date.year + value)
            return [int(next_date.timestamp())], None
        all_dates = [from_date.replace(year=year) for year in range(from_date.year + value, to_date.year, value)]
        return [int(d.timestamp()) for d in all_dates]
    
    # should not reach here
    return [], f"unknown unit: {unit}"
