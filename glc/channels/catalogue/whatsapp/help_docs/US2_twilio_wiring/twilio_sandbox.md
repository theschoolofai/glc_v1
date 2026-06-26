## Twilio website setup for WhatsApp Sandbox

### 1. Create or log in to Twilio

1. Go to [Twilio Console](https://console.twilio.com/).
2. Complete account signup and verify your email and phone number.
3. From the Twilio Console home/account area, note:
   - `Account SID`
   - `Auth Token`

These are the credentials you will later place in your local `.env`. 

---

### 2. Open the WhatsApp Sandbox page

In the Twilio Console:

1. Open **Messaging**.
2. Go to **Try it out**.
3. Click **Send a WhatsApp message**.

On this page, Twilio shows the **WhatsApp Sandbox** details, including: [web:24][web:25][web:31]

- The sandbox WhatsApp number.
- Your account’s unique sandbox join code.
- A QR code that can prefill the join message.
- Sandbox settings for inbound webhook URLs.

If Twilio asks you to accept or confirm WhatsApp Sandbox terms, do that first to activate the sandbox. [web:21]

---

### 3. Join the sandbox from your WhatsApp mobile app

From your personal phone:

1. Open **WhatsApp**.
2. Start a chat with the sandbox number shown in Twilio Console.
3. Send the exact join message shown on the page:

```text
join <your sandbox code>
```

Example:

```text
join white-butterfly
```

Twilio should reply in WhatsApp confirming that your phone number has joined the sandbox. [web:21][web:31]

Alternative:

- Scan the QR code shown on the Twilio Sandbox page.
- WhatsApp will open with the join message prefilled.
- Send that message to complete the join. [web:21][web:28][web:31]

---

### 4. Confirm sandbox is ready

After the join succeeds, confirm you now have all of these from the Twilio website: [web:21][web:24][web:31]

- `Account SID`
- `Auth Token`
- Sandbox WhatsApp number
- Sandbox join code
- Sandbox settings page access

At least one end user must join the sandbox before Twilio can send or receive WhatsApp sandbox messages for that number. [web:21]

---

### 5. Optional next step in Twilio Console

Still on the WhatsApp Sandbox page, open **Sandbox Settings** and locate:

- **When a message comes in**
- **Status callback URL** (if you plan to track delivery updates)

For US-2, this is where you will later paste your tunnel URL, such as an ngrok or cloudflared endpoint pointing to your local WhatsApp adapter route. [web:25][web:34]

---

### 6. What “done” looks like

You can consider Twilio website setup complete when:

- Your Twilio account is active.
- You have saved `Account SID` and `Auth Token`.
- You reached **Messaging → Try it out → Send a WhatsApp message**.
- Your personal WhatsApp number sent the `join <code>` message.
- Twilio confirmed the sandbox join in WhatsApp. [web:21][web:24][web:31]

## Twilio WhatsApp: Env setup and send test

### 7. Environment variables

Create a `.env` file in your project root (gitignored) with:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_SANDBOX_NUMBER=whatsapp:+14155238886      # From WhatsApp Sandbox page
TWILIO_TEST_TO=whatsapp:+91xxxxxxxxxx           # Your phone in WhatsApp format
```

Values:

- `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`: From Twilio Console → Account (Project) settings.
- `TWILIO_SANDBOX_NUMBER`: The WhatsApp sandbox number shown on the **WhatsApp Sandbox** page.
- `TWILIO_TEST_TO`: Your personal WhatsApp number with `whatsapp:` prefix and country code.

Install dependencies:

```bash
pip install twilio python-dotenv
```

---

### 8. Send a WhatsApp message using Python

```python
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")

client = Client(account_sid, auth_token)

message = client.messages.create(
    from_=os.getenv("TWILIO_SANDBOX_NUMBER"),
    to=os.getenv("TWILIO_TEST_TO"),
    body="Twilio WhatsApp sandbox wiring test from .env",
)

print("Message SID:", message.sid)
print("Status:", message.status)
```

Notes:

- Make sure your `TWILIO_TEST_TO` number has **joined the WhatsApp sandbox** by sending the `join <code>` message shown on the sandbox page.
- For US-2, this one script is enough to prove real-world Twilio wiring works end-to-end (Twilio → WhatsApp).