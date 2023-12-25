import os

import json
import time
import traceback

# reminders is a custom package with util functions for dynamodb, openai, whatsapp and time conversions.
import reminders.dynamodb as db
import reminders.whatsapp as wa
import reminders.utils as utils
import reminders.handler_v2 as handler_v2
import reminders.setup_v2 as setup_v2

def handle_message(event, whatsapp_enabled=True):
    tim = os.environ["TIM_PHONE_NUMBER"]
    body = json.loads(event.get("body"))
    # extract contact info from whatsapp request.
    value = body["entry"][0]["changes"][0]["value"]

    if ("contacts" not in value) or ("messages" not in value):
        if "statuses" in value:
            # TODO: handle `status delivered` whatsapp callback
            return
        print(f"Could not parse body: {value}")
        return

    wa_id = value["contacts"][0]["wa_id"]
    msg = value["messages"][0]
    msg_id = msg["id"]
    from_number = msg["from"]
    timestamp = int(msg["timestamp"])  # should be utc (AWS device)

    client = db.get_client()
    # fetch user and their events via dynamoDB.
    user, err = db.get_user(client, wa_id) # user is a dict.
    # todo: what do we do if user exists but we can't fetch it?
    if err:
        utils.log_msg(user, f"Could not get user: {err}")
    # create user if not exists
    if not user:
        user = {
            "wa_id": wa_id,
            "user_name": "",
            "user_timezone": "",
            "conversation": [],
            "events": [],
            "subscription": {"subID": "", "subStatus": ""},
            "message_ids": [],
        }
        err = db.create_user(client, user)
        if err:
            utils.log_msg(user, f"create_user error {err}")
            wa.send_message(from_number, "Sorry there was an error 😔 let's try again later")
            return

    is_user_setup = user["user_name"] and user["user_timezone"]

    if msg["type"] == "text":
        # extract body from whatsapp_request.
        usr_msg = msg["text"]["body"]
    elif msg["type"] == "audio":
        # if wa_id == TIM:
        #     media_id = msg["audio"]["id"]
        #     url = wa.get_media_url(media_id)
        #     ok = wa.download_media(url, out_path=f"{media_id}.ogg")
        #     err_msg = "Sorry, I couldn't download your voice message 😔 let's try again later."
        #     if not ok:
        #         wa.send_message(wa_id, err_msg)
        #         return
        #     utils.convert_ogg_to_mp3(f"{media_id}.ogg", f"{media_id}.mp3")
        #     usr_msg = audio.transcribe(path=f"{media_id}.mp3")
        #     if not usr_msg:
        #         wa.send_message(wa_id, err_msg)
        #         return
        #     os.remove(media_id)
        #     wa.send_message(TIM, f"You sent: {usr_msg}")
        #     return
        wa.send_message(wa_id, "I can't receive voice texts for now but sit tight, I'm working on it! 😊")
        return
    elif msg["type"] == "button":
        # button can only be a response to the consent request.
        # extract payload from whatsapp_request.
        usr_msg = msg["button"]["payload"]

        consent_msg = "I consent"
        non_consent_msg = "I don't consent, bye!"
        email = "hello@mindyreminders.com"
        if usr_msg == consent_msg:
            # fetch user and their events via dynamoDB.
            err = db.update_user_consent(client, wa_id=wa_id, consent=True)
            if is_user_setup:
                wa.send_message(wa_id, f"Thanks 😊 to update your consent or request your data, send an email to {email}. With that out of the way, how can I help?")
            else:
                wa.send_message(wa_id, f"Thanks 😊 to update your consent or request your data, send an email to {email}. Now let's get you set up! What's your name?")
            return
        elif usr_msg == non_consent_msg:
            err = db.update_user_consent(client, wa_id=wa_id, consent=False)
            wa.send_message(wa_id, "Sorry to see you go 😢 if you change your mind, let me know!")
            return
        else:
            return
    else:
        utils.log_msg(user, f"Can't handle message type: {msg['type']}")
        wa.send_message(wa_id, "Sorry, I can only receive texts for now 😊")
        return

    # USER LOCK
    # mark user as locked to prevent concurrent updates
    wait_time = 5
    cumulative_wait_time = 0
    max_wait_time = 60  # seconds
    while wa_id == tim and user.get("locked", False) and int(user.get("locked_ts", "0")) > utils.utc_now_ts() - 5 * 60:
        if cumulative_wait_time == 0:
            utils.log_msg(user, f"User id: {wa_id} marked as locked. Waiting {max_wait_time} seconds...")
        time.sleep(wait_time)
        cumulative_wait_time += wait_time
        user, err_get_user = db.get_user(client, wa_id)
        if not user or err_get_user:
            utils.log_msg(user, f"User id: {wa_id} marked as locked and can't get user object. Aborting.")
            return
        if cumulative_wait_time >= max_wait_time:
            utils.log_msg(user, f"User id: {wa_id} marked as locked. Aborting.")
            return

    err = db.mark_user_as_locked(client, wa_id)
    if err:
        utils.log_msg(user, f"mark_user_as_locked error {err}")
        # wa.send_message(wa_id, "Sorry there was an error 😔 let's try again later")
        # db.mark_user_as_unlocked(client, wa_id=wa_id)
        # return

    # MESSAGE IDS
    for past_msg_id in user.get("message_ids", []):
        if past_msg_id != msg_id:
            continue
        utils.log_msg(user, f"event already processed: msg={msg}")
        db.mark_user_as_unlocked(client, wa_id=wa_id)
        return

    # check that msg_id not already in conversation
    for prev_msg in user.get("conversation", []):
        if not (msg_id and prev_msg.get("id", "") == msg_id):
            continue
        db.mark_user_as_unlocked(client, wa_id=wa_id)
        return

    db.update_message_ids(client=client, wa_id=wa_id, prev_ids=user.get("message_ids", []), msg_id=msg_id)

    # GDPR CONSENT FOR EU COUNTRIES
    country_code = utils.country_code_from_wa_id(wa_id)
    is_eu_country = utils.is_eu_country(country_code)

    if not user.get("consent", False) and (is_eu_country or wa_id == tim):
        # right now we'll continue sending opt in even if user never clicks on a button.
        wa.send_opt_in(wa_id)
        err = db.mark_user_as_unlocked(client, wa_id=wa_id)
        return

    events_v1 = []
    if user.get("events_v1", []):
        events_v1, err = db.get_events(client, user.get("events_v1", [])) # events is a list of dicts.
        # todo: what do we do if events evists but there was an error?
    events_v2 = user.get("events_v2", [])
    events = events_v1 + events_v2
    
    # count number of messages that are not part of setup.
    # TODO: handle case where user is trying to use mindy as chatgpt.
    num_messages = 0
    for prev_msg in user["conversation"]:
        if prev_msg.get("type", "") in ["error", "request", "command"]:
            continue
        # setup messages are included because some people use Mindy as chatGPT.
        num_messages += 1

    if not utils.is_vip(user["wa_id"])\
        and (user.get("subscription", {}).get("subStatus", "") != "active")\
        and num_messages >= 100:
        db.mark_user_as_unlocked(client, wa_id=wa_id)
        if not whatsapp_enabled:
            return
        un = user.get("user_name", "")
        un_with_space = f" {un}" if un else ""
        # create new auth token and redirect to stripe checkout directly
        # token = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(8))
        # url = f"https://mindyreminders.com/mindy/subscribe?waID={wa_id}&token={token}"
        url = "https://mindyreminders.com/account"
        wa_msg = f"Sorry{un_with_space}, you reached the limit of the free version... 😔 But you can sign up for a subscription here! {url} 😊"
        wa.send_message(wa_id, wa_msg)
        return
    
    # increment message count
    err_stats = db.set_user_stats(client=client, wa_id=wa_id, stats=user["stats"], conversation=user["conversation"], message_inc=1, reminder_inc=0)
    if err_stats:
        utils.log_msg(user, f"set_user_stats error: {err_stats}")
    # add user to DAUs
    err_dau = db.add_user_to_dau(client, wa_id=wa_id, is_user_setup=is_user_setup)
    if err_dau:
        utils.log_msg(user, f"Could not add user to DAU: {err_dau}")

    # code path 1: setup user if missing info.
    if not is_user_setup:
        try:
            setup_v2.run(usr_msg, user=user, timestamp=timestamp, client=client)
        except Exception as e:
            utils.log_msg(user, f"Setup exception: {traceback.format_exc()}")
        err = db.mark_user_as_unlocked(client, wa_id=wa_id)
        if err:
            utils.log_msg(user, f"mark_user_as_unlocked error: {err}")
        return

    try:
        handler_v2.run(
            msg=usr_msg,
            msg_id=msg_id,
            user=user,
            timestamp=timestamp,
            events=events,
            client=client
        )
    except Exception as e:
        utils.log_msg(user, f"handler_v2 exception: {traceback.format_exc()}")
        if utils.is_vip(user["wa_id"]):
            wa.send_message(tim, f"VIP Exeption ({user['user_name']}):\nOriginal message:{usr_msg}\n{traceback.format_exc()}")
    err = db.mark_user_as_unlocked(client, wa_id=wa_id)
    if err:
        utils.log_msg(user, f"mark_user_as_unlocked error: {err}")
    return