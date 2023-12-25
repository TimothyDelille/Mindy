import os
import requests
import json

import reminders.dynamodb as db
import reminders.utils as utils

# verify performs the whatsapp verification process when setting up the webhook.
def verify(event):
    verify_token = os.environ["WHATSAPP_VERIFY_TOKEN"]  # generated using import uuid; uuid.uuid4().hex
    params = event.get("queryStringParameters", {})
    mode = params.get('hub.mode', '')
    token = params.get('hub.verify_token', '')
    challenge = params.get('hub.challenge', '')
    if mode == 'subscribe' and token == verify_token:
        print(f"Returning challenge: {challenge}")
        return challenge
    else:
        print(f"Bad request. Mode={mode}, verify_token={token}")
        return -1

# send_message takes a contact_id and outbound_message_body
# and sends it to the whatsapp user.
def send_message(contact_id, body):
    whatsapp_token = os.environ["WHATSAPP_TOKEN"]
    headers = {
        'Authorization': f'Bearer {whatsapp_token}',
        'Content-Type': 'application/json',
    }

    json_data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": contact_id,
        "type": "text",
        "text": {
            "body": body
        }
    }
    phone_number_id = os.environ.get('PHONE_NUMBER_ID')
    response = requests.post(
        f'https://graph.facebook.com/v16.0/{phone_number_id}/messages',
        headers=headers,
        json=json_data)
    if response.status_code != 200:
        print(f"whatsapp.send_message error: {response.text}")

# send takes care of:
# - appending the assistant's message to history, with correct type
# - updating user conversation history
# - sending message via WhatsApp
def send(msg, user, client, hist, type_=""):
    # todo: add safeguard so that user never sees something for the manager.
    hist.append({"role": "assistant", "content": msg, "timestamp": utils.utc_now_ts(), "type": type_})
    print(f"Sending to user: {msg}")

    # update history
    formatted_hist = [
        {
            "role": msg["role"],
            "text": msg["content"],
            "type": msg.get("type", ""),
            "timestamp": msg["timestamp"],
            "version": "2",
            "id": msg.get("id", ""),
        } for msg in hist if msg.get("exclude", False) == False
    ]
    db.update_user_conversation(client, user["wa_id"], formatted_hist)
    if os.environ.get("WHATSAPP_DISABLED") == "True":
        return
    send_message(user["wa_id"], msg)

# TEMPLATES
TEMPLATES = {
    "reminders_en": {"name": "reminders_message", "code": "en_US"},
    "reminders_fr": {"name": "reminders_message", "code": "fr"},
    "opt_in": {"name": "opt_in", "code": "en"},
    "feature_updates": {"name": "feature_updates", "code": "en"},
}

def send_reminder_en(contact_id, text):
    return send_template(contact_id, TEMPLATES["reminders_en"]["name"], TEMPLATES["reminders_en"]["code"], [text])

def send_reminder_fr(contact_id, text):
    return send_template(contact_id, TEMPLATES["reminders_fr"]["name"], TEMPLATES["reminders_en"]["code"], [text])

def send_opt_in(contact_id, email="justtellmeapp@gmail.com"):
    return send_template(contact_id, TEMPLATES["opt_in"]["name"], TEMPLATES["opt_in"]["code"], [email])

def send_template(contact_id, template_name, language_code, params):
    whatsapp_token = os.environ.get("WHATSAPP_TOKEN")
    headers = {
        'Authorization': f'Bearer {whatsapp_token}',
        'Content-Type': 'application/json',
    }

    json_data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": contact_id,
        "type": "template",
        "template": {
                "name": template_name,
                "language": {
                "code": language_code
            },
            "components": [
            {
                "type": "body",
                "parameters": [
                    {
                        "type": "text",
                        "text": param
                    } for param in params
                ]
            }
            ]
        }
    }
    phone_number_id = os.environ.get('PHONE_NUMBER_ID')
    response = requests.post(
        f'https://graph.facebook.com/v16.0/{phone_number_id}/messages',
        headers=headers,
        json=json_data)
    if response.status_code != 200:
        print(f"whatsapp.send_message error: {response.text}")

# ----- AUDIO -----
def get_media_url(media_id):
    url = f'https://graph.facebook.com/v16.0/{media_id}'
    whatsapp_token = os.environ.get("WHATSAPP_TOKEN")
    headers = {
        'Authorization': f'Bearer {whatsapp_token}',
        'Content-Type': 'application/json',
    }
    response = requests.get(url, headers=headers)
    print(response.json())
    try:
        return response.json()["url"]
    except Exception as _:
        return None

def download_media(url, out_path):
    whatsapp_token = os.environ.get("WHATSAPP_TOKEN")
    headers = {
        'Authorization': f'Bearer {whatsapp_token}',
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        with open(out_path, "wb") as file:
            file.write(response.content)
        return True
    else:
        return False



