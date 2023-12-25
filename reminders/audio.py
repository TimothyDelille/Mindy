import requests
import os

# WIP: this does not work yet.
def transcribe(path):
    url = "https://api.openai.com/v1/audio/transcriptions"
    api_key = os.environ["OPENAI_KEY"]

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    files = {
        "file": open(path, "rb"),
    }

    data = {
        "model": "whisper-1",
    }

    response = requests.post(url, headers=headers, files=files, data=data)
    print(response.json())
    if response.status_code == 200:
        return response.json()["data"]["text"]
    else:
        return None
