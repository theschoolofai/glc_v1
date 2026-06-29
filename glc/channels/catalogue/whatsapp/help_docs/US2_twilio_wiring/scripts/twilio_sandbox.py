import os

from dotenv import load_dotenv
from twilio.rest import Client


def send_sandbox_message():
    load_dotenv()
    acc_sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")

    if not acc_sid or not token:
        print("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN")
        return

    from_number = os.getenv("TWILIO_WHATSAPP_FROM")
    to_number = os.getenv("TWILIO_TEST_TO")
    if not from_number or not to_number:
        print("Missing TWILIO_WHATSAPP_FROM or TWILIO_TEST_TO")
        return

    print(f"acc_sid {acc_sid}, token {token[:-4]}...")

    client = Client(username=acc_sid, password=token)

    message = client.messages.create(
        from_=from_number,
        to=to_number,
        body="Twilio sandbox wiring test from .env",
    )

    message = client.messages(message.sid).fetch()
    print("Status:", message.status)
    print("To:", message.to)
    print("From:", message.from_)
    print("Error code:", message.error_code)
    print("Error message:", message.error_message)
    print("After Sandbox Message")


if __name__ == "__main__":
    send_sandbox_message()
