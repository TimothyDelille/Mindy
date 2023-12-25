# time utils
import os
import pendulum

from reminders import whatsapp as wa

TIME_FORMAT = "dddd, YYYY-MM-DD HH:mm:ss"
def utc_now():
    return pendulum.now(tz="UTC")

def utc_now_ts():
    return int(utc_now().timestamp())

def from_timestamp(timestamp, tz):
    dt = pendulum.from_timestamp(timestamp, tz="UTC")
    dt = dt.in_timezone(tz)
    return dt

def utc_to_usr_local_str(timestamp, tz, fmt=TIME_FORMAT):
    dt = from_timestamp(timestamp, tz)
    return dt.format(fmt)

def usr_local_str_to_utc(dt_str, tz, fmt=TIME_FORMAT):
    dt = pendulum.from_format(dt_str, fmt, tz=tz)
    return int(dt.timestamp())

def valid_timezone(timezone):
    try:
        pendulum.now(tz=timezone)
        return True
    except:
        return False

# country utils
import phonenumbers
def country_code_from_wa_id(wa_id):
    # Parse the string to a PhoneNumber object
    try:
        x = phonenumbers.parse(f"+{wa_id}")
        # Get region code
        region_code = phonenumbers.region_code_for_country_code(x.country_code)
        return region_code
    except Exception as _:
        print(f"Could not parse phone number: {wa_id}")
        return ""


def is_eu_country(country_code):
    eu_countries = [
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
    ]
    return country_code.upper() in eu_countries

# # audio utils
# from pydub import AudioSegment
# # Convert OGG to MP3
# def convert_ogg_to_mp3(ogg_file_path, mp3_file_path):
#     ogg_audio = AudioSegment.from_file(ogg_file_path, format="ogg")
#     ogg_audio.export(mp3_file_path, format="mp3")

# VIPs
def is_vip(wa_id):
    return wa_id in os.environ["VIPS"].split(",")

# log_msg prints the message and optionally sends it to Tim for debugging.
def log_msg(user, msg):
    tim = os.environ["TIM_PHONE_NUMBER"]
    print(msg)
    if user.get('wa_id', "") == tim and user.get("verbose", False):
        wa.send_message(tim, msg)