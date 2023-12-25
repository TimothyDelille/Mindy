import json
import os
import reminders.utils as utils

import boto3
from botocore.exceptions import ClientError

USERS_TABLE = "RemindersUsers"
EVENTS_TABLE = "RemindersEvents"
FEEDBACK_TABLE = "MindyFeedback"
DAU_TABLE = "daily_active_users"

BUCKET_WINDOW = 6  # in minutes. Should be >= event bridge rate.

def get_client():
    return boto3.client("dynamodb")

# ----- USERS -----
def create_user(client, user):
    if "wa_id" not in user:
        return "wa_id not in user dict"
    if not user["wa_id"]:
        return "wa_id is null"
    # user is dict that contains keys wa_id, user_name, user_language, user_timezone
    try:
        response = client.put_item(
            TableName=USERS_TABLE,
            Item={
                "wa_id": {"S": user["wa_id"]},
                "user_name": {"S": user["user_name"]},
                "user_timezone": {"S": user["user_timezone"]},
                "conversation": {"L": []},
                "events": {"L": []},
                "events_v2": {"L": []},
                "consent": {"BOOL": False}, # was consent collected?
            },
            ConditionExpression="attribute_not_exists(wa_id)"
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return response
    except Exception as e:
            return e
    return ""

# returns user dict, error string
def get_user(client, wa_id: str):
    try:
        response = client.get_item(
            TableName=USERS_TABLE, 
            Key={"wa_id": {"S": wa_id}},
            AttributesToGet=[
                "wa_id", 
                "user_name", 
                "user_timezone", 
                "conversation", 
                "events",
                "events_v2", 
                "consent",
                "locked",
                "locked_ts",
                "message_ids",
                "stats",
                "verbose", # for me only
            ], 
        )

        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return {}, json.dumps(response["Error"])

        if "Item" not in response:
            return {}, ""
        
        item = response["Item"]

        conversation = []
        for msg in item.get("conversation", {}).get("L", []):
            m = msg.get("M", {})
            try:
                timestamp = int(m.get("timestamp", {}).get("N", "0"))
            except:
                print(f"Error parsing timestamp: {m.get('timestamp', {}).get('N', '0')}")
                timestamp = 0
            conversation.append({
                "text": m.get("text", {}).get("S", ""),
                "timestamp": timestamp,
                "role": m.get("role", {}).get("S", ""),
                "setup": m.get("setup", {}).get("S", ""),
                "type": m.get("type", {}).get("S", ""),
                "version": m.get("version", {}).get("S", ""),
                "id": m.get("id", {}).get("S", ""),
            })

        events_v1 = []
        for e in item.get("events", {}).get("L", []):
            m = e.get("M", {})
            events_v1.append(
                {
                    "ts_bucket": m.get("ts_bucket", {}).get("N", "-1"),
                    "event_id": m.get("event_id", {}).get("S", ""),
                },
            )

        events_v2 = []
        for e in item.get("events_v2", {}).get("L", []):
            m = e.get("M", {})
            try:
                from_date = int(m.get("from_date", {}).get("N", "-1"))
            except:
                from_date = -1
            try:
                to_date = int(m.get("to_date", {}).get("N", "-1"))
            except:
                to_date = -1
            events_v2.append(
                {
                    "ts_bucket": m.get("ts_bucket", {}).get("N", ""),  # legacy
                    "event_id": m.get("event_id", {}).get("S", ""),
                    "event_name": m.get("event_name", {}).get("S", ""),
                    "from_date": from_date,
                    "from_date_str": m.get("from_date_str", {}).get("S", ""),
                    "to_date": to_date,
                    "to_date_str": m.get("to_date_str", {}).get("S", ""),
                    "frequency": m.get("frequency", {}).get("S", ""),
                    "children": [
                        {
                            "ts_bucket": c.get("M", {}).get("ts_bucket", {}).get("N", ""),
                            "event_id": c.get("M", {}).get("event_id", {}).get("S", ""),
                        } for c in m.get("children", {}).get("L", [])
                    ],
                    "version": "2",
                }
            ) 
        subscription_map = item.get("subscription", {}).get("M", {})
        subscription = {
            "subID": subscription_map.get("subID", {}).get("S", ""),
            "subStatus": subscription_map.get("subStatus", {}).get("S", ""),
        }
        
        stats = item.get("stats", {}).get("M", {})
        try:
            messages_sent = int(stats.get("messages_sent", {}).get("N", "0"))
        except:
            print("Error parsing messages_sent: ", stats.get("messages_sent", {}).get("N", "0"))
            messages_sent = 0
        try:
            reminders_created = int(stats.get("reminders_created", {}).get("N", "0"))
        except:
            print("Error parsing reminders_created: ", stats.get("reminders_created", {}).get("N", "0"))
            reminders_created = 0
        try:
            creation_ts = int(stats.get("creation_ts", {}).get("N", "0"))
        except:
            print("Error parsing creation_ts: ", stats.get("creation_ts", {}).get("N", "0"))
            creation_ts = 0
        try:
            last_active_ts = int(stats.get("last_active_ts", {}).get("N", "0"))
        except:
            print("Error parsing last_active_ts: ", stats.get("last_active_ts", {}).get("N", "0"))
            last_active_ts = 0

        stats = {
            "messages_sent": messages_sent,
            "active_days": stats.get("active_days", {}).get("SS", []),
            "reminders_created": reminders_created,
            "creation_ts": creation_ts,
            "last_active_ts": last_active_ts,
        }

        # last 3 message ids. Used to make sure we don't process the same message twice.
        message_ids = [m.get("S", "") for m in item.get("message_ids", {"L": []})["L"]]
        message_ids = [m for m in message_ids if m != ""]
        return {
            "wa_id": item["wa_id"]["S"],
            "user_name": item.get("user_name", {}).get("S", ""),
            "user_timezone": item.get("user_timezone", {}).get("S", "UTC"),
            "subscription": subscription,
            "conversation": conversation,
            "events_v1": events_v1,
            "events_v2": events_v2,
            "consent": item.get("consent", {"BOOL": False})["BOOL"],
            "locked": item.get("locked", {"BOOL": False})["BOOL"],
            "locked_ts": item.get("locked_ts", {"N": "0"})["N"],
            "message_ids": message_ids,
            "stats": stats,
            "verbose": item.get("verbose", {"BOOL": False})["BOOL"],
        }, None
    except Exception as e:
        return {}, e
    
def set_verbosity(client, wa_id, verbose=False):
    if wa_id != os.environ["TIM_PHONE_NUMBER"]:
        return
    
    try:
        response = client.update_item(
            TableName=USERS_TABLE,
            Key={
                "wa_id": {
                    "S": wa_id,
                },
            },
            UpdateExpression="SET verbose = :v",
            ExpressionAttributeValues={
                ":v": {
                    "BOOL": verbose,
                },
            },
            ReturnValues="NONE",
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(response["Error"])
        return None
    except Exception as e:
        return json.dumps(e)
    

def set_user_stats(client, wa_id, stats, conversation=[], message_inc=0, reminder_inc=0):
    # stats is a dictionary containing:
    # - messages sent
    # - unique active days (string set)
    # - reminders created
    # - creation date (timestamp of first message)
    # - last active date (timestamp of last message)
    messages_sent = stats.get("messages_sent", 0) + message_inc
    date = utils.utc_now().strftime("%Y-%m-%d")
    active_days = stats.get("active_days", [])
    if date not in active_days:
        active_days.append(date)
    reminders_created = stats.get("reminders_created", 0) + reminder_inc

    creation_ts = stats.get("creation_ts", 0)
    if creation_ts == 0 and len(conversation) > 0:
        # get min timestamp from conversation
        creation_ts = min([int(m["timestamp"]) for m in conversation if m["role"] == "user"])

    # last_active_ts = stats.get("last_active_ts", 0)
    # if len(conversation) > 0:
    #     # get max timestamp from conversation
    #     last_active_ts = max([int(m["timestamp"]) for m in conversation if m["role"] == "user"])
    last_active_ts = utils.utc_now_ts()

    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET stats = :s",
            ExpressionAttributeValues={
                ":s": {"M": {
                    "messages_sent": {"N": str(messages_sent)},
                    "active_days": {"SS": active_days},
                    "reminders_created": {"N": str(reminders_created)},
                    "creation_ts": {"N": str(creation_ts)},
                    "last_active_ts": {"N": str(last_active_ts)},
                }}
            },
            ReturnValues="NONE"
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

def update_user_consent(client, wa_id, consent):
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET consent = :c",
            ExpressionAttributeValues={
                ":c": {"BOOL": consent}
            },
            ReturnValues="NONE"
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

def update_user_name(client, wa_id, name):
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET user_name = :n",
            ExpressionAttributeValues={":n": {"S": name}},
            ReturnValues="NONE"
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

def update_user_timezone(client, wa_id, timezone):
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET user_timezone = :tz",
            ExpressionAttributeValues={":tz": {"S": timezone}},
            ReturnValues="NONE"
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

# maintain a list of last 3 received ids.
# if the message id is in this list, it means we already processed it.
def update_message_ids(client, wa_id, prev_ids, msg_id):
    try:
        ids = [msg_id] + prev_ids[:2]
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET message_ids = :m",
            ExpressionAttributeValues={":m": {"L": [{"S": id_} for id_ in ids]}},
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e

# implement "lock" to prevent multiple concurrent updates
# while we process a user's message.
def mark_user_as_locked(client, wa_id):
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET locked = :l, locked_ts = :ts",
            # add condition that locked should be false
            ConditionExpression=" attribute_not_exists(locked) OR locked = :f OR attribute_not_exists(locked_ts) OR locked_ts < :tslimit",
            ExpressionAttributeValues={
                ":l": {"BOOL": True},
                ":f": {"BOOL": False},
                ":ts": {"N": str(utils.utc_now_ts())},
                ":tslimit": {"N": str(utils.utc_now_ts() - 15*60)},  # 15 minutes limit
            },
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e

# unlock user once we are done processing the message
def mark_user_as_unlocked(client, wa_id):
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET locked = :l",
            ExpressionAttributeValues={":l": {"BOOL": False}},
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e

def update_user_conversation(client, wa_id: str, messages: list):
    # messages is a list of dict with keys text, timestamp and role (user or assistant)
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={'wa_id': {"S": wa_id}},
            UpdateExpression="SET conversation = list_append(conversation, :m)",
            ExpressionAttributeValues={
                ':m': {"L":
                [
                    {"M": {
                        "text": {"S": msg["text"]},
                        "timestamp": {"N": str(msg["timestamp"])},
                        "role": {"S": msg["role"]},
                        "setup": {"S": msg.get("setup", "false")},
                        "type": {"S": msg.get("type", "")},
                        "version": {"S": msg.get("version", "")},
                        "id": {"S": msg.get("id", "")},
                    }}
                    for msg in messages
                ]
                },
            },
            ReturnValues="NONE"
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

def update_user_events(client, wa_id: str, events: list):
    # events: list of dict with keys ts_bucket and event_id
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET events = list_append(events, :e)",
            ExpressionAttributeValues={
                ":e": {
                    "L": [
                        {
                            "M": {
                                "ts_bucket": {"N": str(e["ts_bucket"])}, 
                                "event_id": {"S": e["event_id"]}
                            }
                        } for e in events
                    ]
                }
            },
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

def update_user_events_v2(client, wa_id: str, events: list):
    # events: list of dict with keys ts_bucket and event_id
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET events_v2 = list_append(if_not_exists(events_v2, :empty_list), :e)",
            ExpressionAttributeValues={
                ":e": {
                    "L": [{
                            "M": {
                                "ts_bucket": {"N": str(e["ts_bucket"])},  # legacy
                                "event_id": {"S": e["event_id"]},
                                "event_name": {"S": e["event_name"]},
                                "from_date": {"N": str(e["from_date"])},
                                "from_date_str": {"S": e["from_date_str"]},
                                "to_date": {"N": str(e["to_date"])},
                                "to_date_str": {"S": e["to_date_str"]},
                                "frequency": {"S": e["frequency"]},
                                "children": {"L": [
                                    {"M": {
                                        "ts_bucket": {"N": c["ts_bucket"]},
                                        "event_id": {"S": c["event_id"]},
                                    }} for c in e["children"]
                                ]}
                        } for e in events
                    }],
                },
                ":empty_list": {"L": []},
            },
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None


# replaces user events every time.
def set_user_events(client, wa_id: str, events: list):
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET events = :e",
            ExpressionAttributeValues={
                ":e": {
                    "L": [
                        {
                            "M": {
                                "ts_bucket": {"N": str(e["ts_bucket"])},
                                "event_id": {"S": e["event_id"]}
                            }
                        } for e in events
                    ]
                }
            },
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

def set_user_events_v2(client, wa_id: str, events: list):
    # events: list of dict with keys ts_bucket and event_id
    try:
        resp = client.update_item(
            TableName=USERS_TABLE,
            Key={"wa_id": {"S": wa_id}},
            UpdateExpression="SET events_v2 = :e",
            ExpressionAttributeValues={
                ":e": {
                    "L": [{
                            "M": {
                                "ts_bucket": {"N": str(e.get("ts_bucket", "0"))},  # legacy soon
                                "event_id": {"S": e["event_id"]},
                                "event_name": {"S": e["event_name"]},
                                "from_date": {"N": str(e["from_date"])},
                                "from_date_str": {"S": e["from_date_str"]},
                                "to_date": {"N": str(e["to_date"])},
                                "to_date_str": {"S": e["to_date_str"]},
                                "frequency": {"S": e["frequency"]},
                                "version": {"S": "2"},
                                "reschedule": {"BOOL": e.get("reschedule", True)},
                                "children": {"L": [
                                    {"M": {
                                        "ts_bucket": {"N": c["ts_bucket"]},
                                        "event_id": {"S": c["event_id"]},
                                    }} for c in e["children"]
                                ]}
                        } for e in events
                    }] if events else [],
                }
            },
            ReturnValues="NONE",
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        return e
    return None

# ----- EVENTS -----
def get_ts_bucket(event_timestamp: int):
    # event_timestamp is in seconds.
    # bucket_window is in minutes: e.g. 5.
    # primary key is a time bucket. One bucket spans 5 minutes.
    # an event set at 9:34 will be pooled with all events between 9:30 and 9:35
    ts_bucket = event_timestamp - event_timestamp % (BUCKET_WINDOW * 60)
    return ts_bucket

def get_event_id(wa_id: str, event_name: str, event_timestamp: str, frequency: str):
    return f"{wa_id}:{event_name}:{str(int(event_timestamp))}:{frequency}" # secondary key

def get_event_id_v2(wa_id, event_name, from_date, to_date, frequency):
    return f"{wa_id}:{event_name}:{from_date}:{to_date}:{frequency}"

def create_event(client, event):
    try:
        event_name = event["event_name"]
        event_timestamp = event["event_timestamp"]
        event_timestamp_str = event["event_timestamp_str"]
        frequency = event["frequency"]
        wa_id = event["wa_id"]
        ts_bucket = event["ts_bucket"]
        event_id = event["event_id"]

        response = client.put_item(
            TableName=EVENTS_TABLE,
            Item={
                "ts_bucket": {"N": str(ts_bucket)},
                "event_id": {"S": event_id},
                "wa_id": {"S": wa_id},
                "event_name": {"S": event_name},
                "event_timestamp": {"N": str(event_timestamp)},
                "event_timestamp_str": {"S": event_timestamp_str},
                "frequency": {"S": frequency},
                "scheduled": {"BOOL": False},
            }
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(response["Error"])

        err = increment_reminder(client, wa_id=wa_id, increment=1)
    except Exception as e:
        return e
    return None

def create_event_v2(
        client,
        wa_id,
        event_id,
        ts_bucket,
        event_name, 
        from_date, 
        from_date_str, 
        to_date,
        to_date_str,
        frequency,
        reschedule=True,
    ):
    try:
        response = client.put_item(
            TableName=EVENTS_TABLE,
            Item={
                "ts_bucket": {"N": str(ts_bucket)},
                "event_id": {"S": event_id},
                "wa_id": {"S": wa_id},
                "event_name": {"S": event_name},
                "event_timestamp": {"N": str(from_date)}, # legacy
                "event_timestamp_str": {"S": from_date_str}, # legacy
                "from_date": {"N": str(from_date)},
                "from_date_str": {"S": from_date_str},
                "to_date": {"N": str(to_date)},
                "to_date_str": {"S": to_date_str},
                "frequency": {"S": frequency},
                "scheduled": {"BOOL": False},
                "version": {"S": "2"},
                "reschedule": {"BOOL": reschedule},  # if reschedule=False, it will not be rescheduled at fire time. (reschedule=False for child events)
            }
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(response["Error"])

        err = increment_reminder(client, wa_id=wa_id, increment=1)
    except Exception as e:
        return e
    return None

def delete_event(client, wa_id, ts_bucket, event_id):
    try:
        resp = client.delete_item(
            TableName=EVENTS_TABLE,
            Key={'ts_bucket': {"N": str(ts_bucket)}, "event_id": {"S": event_id}},
        )
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])

        err = increment_reminder(client, wa_id=wa_id, increment=-1)
    except Exception as e:
        return e
    return None

def get_events(client, events):
    def parse_children(item):
        children = []
        for child in item.get("children", []):
            children.append(
                {
                    "ts_bucket": child.get("ts_bucket", {}).get("N", -1),
                    "event_id": child.get("event_id", {}).get("S", ""),
                }
            )
        return children
    if not events:
        return [], None
    # events = list of dictionaries containing `ts_bucket` and `event_id` keys.
    try:
        unique_keys = []
        for e in events:
            new_key = (e["ts_bucket"], e["event_id"])
            if new_key not in unique_keys:
                unique_keys.append(new_key)
        response = client.batch_get_item(
            RequestItems={EVENTS_TABLE: {"Keys": [{"ts_bucket": {"N": ts}, "event_id": {"S": eid}} for ts, eid in unique_keys]}},
        )
        items = response["Responses"][EVENTS_TABLE]
        results = [
            {
                "ts_bucket": item["ts_bucket"]["N"],
                "event_id": item["event_id"]["S"],
                "wa_id": item["wa_id"]["S"],
                "event_name": item["event_name"]["S"],
                "event_timestamp_str": item.get("event_timestamp_str", {}).get("S", ""),
                "event_timestamp": item.get("event_timestamp", {}).get("N", ""),
                "from_date": item.get("from_date", {}).get("N", ""),
                "from_date_str": item.get("from_date_str", {}).get("S", ""),
                "to_date": item.get("to_date", {}).get("N", ""),
                "to_date_str": item.get("to_date_str", {}).get("S", ""),
                "frequency": item["frequency"]["S"],
                "scheduled": item["scheduled"]["BOOL"],
                "version": item.get("version", {}).get("S", ""),
                "reschedule": item.get("reschedule", {}).get("BOOL", True),
            } for item in items
        ]
        results = sorted(results, key=lambda e: (int(e["event_timestamp"]), e["event_id"]))  # adding e["event_id"] to make sure order is deterministic
        return results, None
    except Exception as e:
        return [], e

def get_upcoming_events(client):
    # returns list of events, error
    now_ts = utils.utc_now_ts()
    ts_bucket = get_ts_bucket(now_ts)

    print(f"Checking ts_bucket={ts_bucket}")

    try:
        response = client.query(
            TableName=EVENTS_TABLE,
            KeyConditionExpression="ts_bucket = :ts",
            FilterExpression="scheduled = :s",
            ExpressionAttributeValues={":ts": {"N": str(ts_bucket)}, ":s": {"BOOL": False}}
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return [], json.dumps(response["Error"])
        items = response["Items"]
        events = [
            {
                "ts_bucket": int(item["ts_bucket"]["N"]),
                "event_id": item["event_id"]["S"],
                "wa_id": item["wa_id"]["S"],
                "event_name": item["event_name"]["S"],
                "event_timestamp_str": item.get("event_timestamp_str", {}).get("S", ""),
                "event_timestamp": item.get("event_timestamp", {}).get("N", ""),
                "from_date": item.get("from_date", {}).get("N", ""),
                "from_date_str": item.get("from_date_str", {}).get("S", ""),
                "to_date": item.get("to_date", {}).get("N", ""),
                "to_date_str": item.get("to_date_str", {}).get("S", ""),
                "frequency": item["frequency"]["S"],
                "scheduled": item["scheduled"]["BOOL"],
                "version": item.get("version", {}).get("S", ""),
            } for item in items
        ]
        return events, None
    except Exception as e:
        return [], e

def mark_event_as_scheduled(client, ts_bucket: int, event_id: str):
    try:
        resp = client.update_item(TableName="RemindersEvents", Key={'ts_bucket': {"N": str(ts_bucket)}, 'event_id': {"S": event_id}}, UpdateExpression="SET scheduled = :s", ExpressionAttributeValues={":s": {"BOOL": True}})
        if resp["ResponseMetadata"]["HTTPStatusCode"] != 200:
            return json.dumps(resp["Error"])
    except Exception as e:
        print(f"mark_event_as_scheduled failed for ts_bucket={ts_bucket}, event_id={event_id} with error: {e}")
        return e
    return None

def get_event_from_index(event_index: str, events):
    # event_index is 1-indexed.
    if not events:
        print("get_event_from_index: events list is empty")
        return dict(), "event list is empty"

    try:
        i = int(event_index)
    except Exception as e:
        return dict(), f"update_event: could not convert event_index to int: {e}"

    if i < 0 or i > len(events) - 1:
        return dict(), f"update_event: could not find event with index: {i - 1}. len(events)={len(events)}"

    return events[i], ""

# ----- FEEDBACK -----
def insert_new_feedback(client, wa_id, feedback_msg):
    try:
        response = client.put_item(
                TableName=FEEDBACK_TABLE,
                Item={
                    "wa_id": {"S": wa_id},
                    "feedback_timestamp": {"S": str(utils.utc_now_ts())},
                    "feedback": {"S": feedback_msg},
                    "reviewed": {"BOOL": False},
                }
            )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            err = json.dumps(response["Error"])
            return err
    except Exception as err:
        return err
    return None

# ----- DAILY ACTIVE USERS -----
def add_user_to_dau(client, wa_id, is_user_setup, date=""):
    if not date:
        date = utils.utc_now().strftime("%Y%m%d")
    try:
        response = client.update_item(
            TableName=DAU_TABLE,
            Key={'date': {"S": date}},
            # increment the count by 1 and add wa_id to the wa_ids set
            UpdateExpression="ADD wa_ids :wset, dau_count :c, dau_count_after_setup :s SET reminders = :r",
            # only update if wa_id not in the wa_ids string set already
            ConditionExpression="attribute_not_exists(wa_ids) OR NOT contains(wa_ids, :w)",
            ExpressionAttributeValues={
                ":wset": {"SS": [wa_id]},
                ":w": {"S": wa_id},
                ":c": {"N": "1"},
                ":s": {"N": "1" if is_user_setup else "0"},
                # map from wa_id to reminder count
                ":r": {"M": {}},
            },
            ReturnValues="NONE" # https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_UpdateItem.html#DDB-UpdateItem-request-ReturnValues
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            err = json.dumps(response["Error"])
            print(f"add_user_to_dau failed with error: {err}")
            return err
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # user already added as dau
            return ""
        print(f"add_user_to_dau failed with error: {err}")
        return err

def increment_reminder(client, wa_id, increment, date=""):
    if not date:
        date = utils.utc_now().strftime("%Y%m%d")
    try:
        response = client.update_item(
            TableName=DAU_TABLE,
            Key={'date': {"S": date}},
            # increment the count by 1 and add wa_id to the wa_ids map (map from wa_id to reminder_count)
            UpdateExpression="ADD reminder_count :c, reminders.#wa_id :c",
            ExpressionAttributeValues={
                ":c": {"N": str(increment)},
            },
            ExpressionAttributeNames={"#wa_id": wa_id},
            ReturnValues="NONE"
        )
        if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
            err = json.dumps(response["Error"])
            print("increment_reminder error: ", err)
            return err
    except Exception as err:
        print("increment_reminder error: ", err)
        return err

# RESET DUMMY USER
def reset_dummy_user(client):
    wa_id = "test"  # same as dummies.DUMMY_WA_ID
    messages = []
    resp = client.update_item(
        TableName="RemindersUsers",
        Key={'wa_id': {"S": wa_id}},
        UpdateExpression="SET conversation = :m, events = :e, user_name = :un, user_timezone = :tz",
        ExpressionAttributeValues={
            ':m': {"L":
            [
                {"M": {
                    "text": {"S": msg["text"]},
                    "timestamp": {"N": str(msg["timestamp"])},
                    "role": {"S": msg["role"]}
                }}
                for msg in messages
            ]
            },
            ':e': {
                "L": []
            },
            ":un": {
                "S": "",
            },
            ":tz": {
                "S": "",
            },
        },
        ReturnValues="NONE"
    )
    return
