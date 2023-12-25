Mindy runs on a lambda function. The entrypoint is `lambda_function.py`. The request is passed to the handler named `lambda_handler`.

When a user sends a message, WhatsApp forwards it to the Lambda function, which treats it and sends a message back to the user via the WhatsApp API.

For reminders, Amazon EventBridge sends a request to the lambda function every 5 minutes to check for reminders. All events found within a 5 minute window are sent in order.

`reminders` is a custom package with util functions for dynamodb, openai, whatsapp and time conversions.
