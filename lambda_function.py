from check_reminders import check_reminders
from handle_message import handle_message
import reminders.whatsapp as wa

# lambda_handler is the entry point for AWS Lambda requests.
# AWS Lambda requires it to take an event and context as input.
# The event input is a dictionary.
def lambda_handler(event, context):
    # code path 1: whatsapp requests verification. Only happens once.
    if event.get("requestContext", {}).get("http", {}).get("method") == "GET":
        return wa.verify(event)
    # code path 2: Amazon EventBridge triggers a reminders check. We look for reminders to send out.
    elif event.get("message", "") == "check_for_reminders":
        # event is coming from Amazon EventBridge. Format is: {"message": "check_for_reminders"}
        check_reminders()
    # code path 3: a user sent a message via WhatsApp and we need to respond.
    else:
        # event is coming from whatsapp.
        # event format for URL invocations: https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html
        handle_message(event)