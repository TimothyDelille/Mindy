import datetime
import sys
import os
reminders_dir = "/Users/timothydelille/mindy/"
sys.path.append(reminders_dir)
import reminders.parser as parser
import reminders.utils as utils

# to run tests: python reminders/unit_tests/parser_tests.py

def test_parser_parse():
    tests = [
        {
            "msg": "create(\"Prendre rendez-vous chez l'ophtalmo\", \"none\", \"none\", \"once\")",
            "expected": [("create", ["Prendre rendez-vous chez l'ophtalmo", "none", "none", "once"])]
        },
        {
            "msg": "create(\"Drink water\", \"Monday, 2023-06-05 16:35:00\", \"Monday, 2023-06-05 17:35:00\", \"every 6 minutes\")",
            "expected": [("create", ["Drink water", "Monday, 2023-06-05 16:35:00", "Monday, 2023-06-05 17:35:00", "every 6 minutes"])]
        },
    ]

    passed = True
    for i, t in enumerate(tests):
        msg = t["msg"]
        expected = t["expected"]
        actual = parser.parse(msg)
        if actual != expected:
            passed = False
            print(f"Failed on test {i}: expected {expected}, got {actual}")
    return passed

def test_parser_transform():
    tests = [
        {
            "fn": "create",
            "args": [
                "drink water",  # event name
                "Monday, 2023-06-05 16:55:00",  # from date
                "none",  # to date
                "every hour",  # frequency
            ],
            "user": {
                "user_timezone": "UTC",
            },
            "error": False,
            "expected": {
                "event_name": "drink water",
                "from_date": utils.usr_local_str_to_utc("Monday, 2023-06-05 16:55:00", "UTC"),
                "from_date_str":  "Monday, 2023-06-05 16:55:00",
                "to_date": -1,
                "to_date_str": "none",
                "frequency": "every hour",
            },
            "reason": "Vanilla. No errors."
        },
        {
            "fn": "create",
            "args": [
                "none",
                "none",
                "drink water",
                "every hour",
            ],
            "user": {
                "user_timezone": "UTC",
            },
            "error": True,
            "expected": {},
            "reason": "from_date cannot be none."
        },
        {
            "fn": "create",
            "args": [
                "2023-06-05 16:55:00",
                "none",
                "drink water",
                "every hour",
            ],
            "user": {
                "user_timezone": "UTC",
            },
            "error": True,
            "expected": {},
            "reason": "from_date format is wrong."
        },
    ]
    passed = True
    for i, t in enumerate(tests):
        expected = t["expected"]
        actual, err = parser.transform(fn=t["fn"], args=t["args"], user=t["user"])

        if not t["error"]:
            if err:
                passed = False
                print(f"Failed on test {i}: expected no error, got {err}")
                
            for k in expected.keys():
                if actual[k] != expected[k]:
                    passed = False
                    print(f"Failed on test {i} for key {k}: expected value {expected[k]}, got {actual[k]}")
        else:
            if not err:
                passed = False
                print(f"Failed on test {i}: expected error, got {err}")
    print("PASSED")
    return passed


if __name__ == "__main__":
    print("test parse...")
    test_parser_parse()
    print("test transform...")
    test_parser_transform()