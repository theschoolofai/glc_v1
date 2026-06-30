# WhatsApp Channel

The WhatsApp channel lets you interact with the agent directly from your WhatsApp account. When you send a message to the configured number, the agent receives it, processes it, and replies — all through WhatsApp.

Two providers are supported:

- **Meta Cloud API** — direct integration with Meta's WhatsApp Business platform. Meta provides a free test account with a pre-provisioned number and access token, so you can be up and running without any business verification or paid plan.
- **Twilio** — a relay service that sits between your server and WhatsApp. Also free to get started with via a trial account, using a shared sandbox number that recipients opt into with a join code.

Both are accessible for testing and both are free to start. The main practical difference is that Meta gives you your own dedicated test number, while Twilio uses a shared sandbox number. Both providers use the same agent and the same message format — the gateway automatically selects the right one per recipient, so you can run both simultaneously.

<table>
  <tr>
    <td align="center"><strong>Meta Cloud API</strong></td>
    <td align="center"><strong>Twilio Sandbox</strong></td>
  </tr>
  <tr>
    <td><img src="assets/screenshots/WhatsApp_Meta_Banner.png" alt="WhatsApp via Meta Cloud API" width="340"/></td>
    <td><img src="assets/screenshots/WhatsApp_Twilio_Banner.png" alt="WhatsApp via Twilio Sandbox" width="340"/></td>
  </tr>
</table>

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Meta Cloud API Setup](#meta-cloud-api-setup)
3. [Twilio Setup](#twilio-setup)
4. [Provider Routing](#provider-routing)
5. [Known Limitations](#known-limitations)
6. [Troubleshooting](#troubleshooting)
7. [Project Structure](#project-structure)

---

## Getting Started

Complete the following three steps before you start:

1. **Enable the WhatsApp channel** — set `whatsapp: {enabled: true}` in `glc/channels.yaml`. By default it is disabled.

2. **Set environment variables** — create a `.env` file at the project root (it is already gitignored). Fill in the variables for the provider(s) you are setting up. You will understand how to fill in each of these as you go through the setup instructions — the table below is just to give you an overview of what is required upfront.

   | Variable | Provider | What it is |
   |---|---|---|
   | `WHATSAPP_PHONE_NUMBER_ID` | Meta | Numeric Phone Number ID from the Meta "Step 1. Try it out" panel |
   | `WHATSAPP_TOKEN` | Meta | Graph API access token — 24-hour (from the panel) or 60-day (via Graph API Explorer) |
   | `WHATSAPP_APP_SECRET` | Meta | App secret from App Settings → Basic → App secret → Show |
   | `WHATSAPP_VERIFY_TOKEN` | Meta | Any string you choose — must match exactly what you enter in the Meta console webhook config |
   | `WHATSAPP_WABA_ID` | Meta | WhatsApp Business Account ID shown on the "Step 1. Try it out" panel |
   | `WHATSAPP_APP_ID` | Meta | Numeric App ID from App Settings → Basic |
   | `TWILIO_ACCOUNT_SID` | Twilio | Account SID from Twilio Console home page |
   | `TWILIO_AUTH_TOKEN` | Twilio | Auth Token from Twilio Console home page — treat as a password |
   | `TWILIO_WHATSAPP_FROM` | Twilio | Sandbox number with `whatsapp:` prefix, e.g. `whatsapp:+14155238886` |
   | `TWILIO_WEBHOOK_URL` | Twilio | Exact public URL configured in Twilio Sandbox Settings — must match character-for-character |

3. **Install the `twilio` package** — `adapter.py` imports from the `twilio` package, which is not yet declared in `pyproject.toml`. Until a separate PR adds it, a clean `uv sync` will not pull it in.
   > **TODO:** install it manually with `uv pip install twilio` if you hit an import error on the Twilio path.

---

## Meta Cloud API Setup

Meta Cloud API is the direct integration with WhatsApp via Meta's developer platform. Messages go directly between your server and Meta — no third-party relay.

### Step 1 — Create a Meta developer app

Go to [developers.facebook.com](https://developers.facebook.com) → **My Apps** → **Create App**.

![App details screen](assets/screenshots/meta_01_app_details.png)

You will be asked to fill in a name and contact email for your app. This is just the developer app container — it does not need to be a real business name.

### Step 2 — Select the WhatsApp use case

On the next screen, select **"Connect with customers through WhatsApp"** as your use case.

![Use case selection](assets/screenshots/meta_02_use_cases.png)

### Step 3 — Attach a Business Portfolio

Meta requires a Business Portfolio to be associated with the app. If you do not have one yet, you will be prompted to create one. An unverified portfolio is fine for testing — no business documents are required at this stage.

![Business portfolio prompt](assets/screenshots/meta_03_business_no_portfolio.png)

If prompted to verify, click **"Verify Later"** to skip and continue.

![Verify later modal](assets/screenshots/meta_04_verify_later_modal.png)

### Step 4 — Finish app creation

Review the summary screen and click **Create App**.

![Overview create app](assets/screenshots/meta_05_overview_create_app.png)

You will land on the app dashboard.

![App dashboard](assets/screenshots/meta_06_dashboard.png)

### Step 5 — Navigate to the WhatsApp setup

From the left sidebar, go to **Use Cases**, find the WhatsApp entry, and click **Customize**.

![Use cases page](assets/screenshots/meta_07_use_cases_page.png)

Then click **Continue** to proceed.

![Customize continue](assets/screenshots/meta_08_customize_continue.png)

### Step 6 — Open the API integration panel

Click **Integrate with API**.

![Integrate with API](assets/screenshots/meta_09_integrate_with_api.png)

You will be asked to confirm your OAuth account.

![OAuth accounts](assets/screenshots/meta_10_oauth_accounts.png)

### Step 7 — Collect your credentials from the "Try it out" panel

You are now on the **Step 1. Try it out** panel. This is where your test credentials live.

![Step 1 Try it out](assets/screenshots/meta_11_step1_try_it_out.png)

From this panel, collect:

- **Phone Number ID** → copy to `WHATSAPP_PHONE_NUMBER_ID`
- **WhatsApp Business Account ID** → copy to `WHATSAPP_WABA_ID`
- Click **Generate new token** → copy to `WHATSAPP_TOKEN` (this token expires in 24 hours)

> **60-day token (optional):** The default 24-hour token must be regenerated frequently. To get a 60-day token, use the [Graph API Explorer](https://developers.facebook.com/tools/explorer/) as described in Step 9 below.

**Send the template message first:** Before the gateway can exchange free-form messages with your phone, Meta requires an initial outbound message from the business number. Use the "Send message" panel to send the pre-approved template to your personal phone number. Then **reply from your phone** — this opens the 24-hour free-form messaging window.

### Step 8 — Retrieve your App Secret

Go to **App Settings → Basic → App secret → Show**.

![App secret](assets/screenshots/meta_12_app_secret.png)

Copy the value → `WHATSAPP_APP_SECRET`. This is used by the gateway to verify the HMAC-SHA256 signature on every inbound webhook — without it, the gateway will reject all incoming messages.

### Step 9 — Get a 60-day token (optional but recommended)

The 24-hour token from the panel must be regenerated before every session. To avoid this, exchange it for a 60-day token using the Graph API Explorer.

![Graph API Explorer](assets/screenshots/meta_13_graph_api_explorer.png)

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your app from the top-right dropdown.
3. Click **Generate Access Token** → select the `whatsapp_business_messaging` and `whatsapp_business_management` permissions.
4. Exchange the short-lived token for a long-lived one using the Graph API Explorer (see [US1_meta_wiring_setup.md](help_docs/US1_meta_wiring/US1_meta_wiring_setup.md) step 10 for the full exchange procedure).
5. Copy the resulting token → `WHATSAPP_TOKEN`.

### Step 10 — Collect your App ID

Your App ID is visible in **App Settings → Basic** at the top of the page, or in the URL of any page in your app dashboard (e.g. `https://developers.facebook.com/apps/123456789/`).

Copy it → `WHATSAPP_APP_ID`.

### Step 11 — Start your tunnel and run the gateway

Open two terminals:

```bash
# Terminal 1 — tunnel
ngrok http 8111
```

```bash
# Terminal 2 — gateway
cd glc_v1
uv sync
uv run glc serve
```

Note the `https://` URL that ngrok prints (e.g. `https://abc123.ngrok-free.app`). You will need this in the next step.

### Step 12 — Register the webhook in the Meta console

1. In the Meta App Dashboard → **WhatsApp → Configuration → Webhook → Edit**.
2. Set **Callback URL** to your tunnel URL (e.g. `https://abc123.ngrok-free.app`).
3. Set **Verify Token** to the same value as `WHATSAPP_VERIFY_TOKEN` in your `.env`.
4. Click **Verify and Save**. Meta sends a one-time GET request containing a `hub.challenge` value — the gateway echoes it back automatically and verification completes.
5. Under **Webhook fields**, click **Subscribe** next to the **messages** field. Without this subscription, Meta will not forward inbound WhatsApp messages to your server.

### Step 13 — Pair your phone number

The gateway requires your phone number to be registered (paired) before it will process your messages or send replies to you. This is a one-time step per installation.

Get your installation token:

```bash
uv run glc token
```

Request a pairing code:

```bash
curl -X POST http://localhost:8111/v1/control/pair \
  -H "Authorization: Bearer <your-token>"
```

The response will contain a 6-digit pairing code. **Send that code as a WhatsApp message from your phone to the test number.** The gateway will confirm pairing — your number is now registered as the owner.

### Step 14 — Send your first message

With the gateway running and your phone paired, send any message from your WhatsApp to the test number. You should receive a reply from the agent within a few seconds.

> **24-hour window reminder:** Meta's re-engagement window means that if more than 24 hours pass without a message from your phone to the test number, the window closes. To reopen it, send any message to the test number first — the gateway does not automatically fall back to Twilio for this case (error `131047`). The automatic Twilio fallback only triggers on a separate error, `131030` (recipient not in Meta's allowed list). See [Provider Routing](#provider-routing) for details.

---

## Twilio Setup

Twilio acts as a relay — inbound WhatsApp messages arrive at Twilio's servers first, then Twilio forwards them to your webhook. You use a shared sandbox number rather than a dedicated registered number.

### Step 1 — Create a Twilio account

Go to [console.twilio.com](https://console.twilio.com) and sign up. Choose the free trial plan — it is sufficient for all testing purposes.

![Choose plan](assets/screenshots/twilio_01_choose_plan.png)

### Step 2 — Collect your Account SID and Auth Token

After signing in, your **Account SID** and **Auth Token** are shown on the Console home page.

![Account credentials](assets/screenshots/twilio_02_account_credentials.png)

Copy them to your `.env`:
- Account SID → `TWILIO_ACCOUNT_SID`
- Auth Token → `TWILIO_AUTH_TOKEN` (treat this as a password — do not commit it)

### Step 3 — Activate the WhatsApp Sandbox

In the Twilio Console, go to **Messaging → Try it out → Send a WhatsApp message**. Accept the sandbox terms when prompted.

![Activate sandbox](assets/screenshots/twilio_03_activate_sandbox.png)

Take note of the sandbox number shown on this page (e.g. `+14155238886`) and copy it → `TWILIO_WHATSAPP_FROM` (with the `whatsapp:` prefix, e.g. `whatsapp:+14155238886`).

### Step 4 — Join the sandbox from your personal phone

Every WhatsApp account that wants to receive messages from the sandbox must opt in by sending a join code. From your personal WhatsApp, send the following to the sandbox number:

```
join <your-sandbox-code>
```

The sandbox code is shown on the Twilio sandbox page (e.g. `join silver-tiger`).

![Join sandbox](assets/screenshots/twilio_04_join_sandbox.png)

Twilio will send a confirmation message back to your phone confirming you have joined.

> **Join codes expire every 3 days.** If messages stop delivering, re-send the join message. Twilio returns error `63016` when the join has expired.

### Step 5 — Start your tunnel and run the gateway

```bash
# Terminal 1 — tunnel
ngrok http 8111
```

```bash
# Terminal 2 — gateway
uv run glc serve
```

Note the `https://` URL printed by ngrok.

### Step 6 — Register the webhook in Twilio console

1. On the Twilio sandbox page, open the **Sandbox Settings** tab.
2. In the **"When a message comes in"** field, enter your tunnel URL followed by the channel path:
   ```
   https://abc123.ngrok-free.app/v1/channels/whatsapp
   ```
3. Click **Save**.
4. Copy the exact URL you just saved → `TWILIO_WEBHOOK_URL` in your `.env`.

> **Critical:** `TWILIO_WEBHOOK_URL` must match the webhook URL in Twilio's console character-for-character — including trailing slashes and `http` vs `https`. Any mismatch causes Twilio's HMAC-SHA1 signature validation to fail and all messages will be silently dropped.

### Step 7 — Pair your phone number

Same pairing flow as Meta — the gateway requires your number to be registered before it processes your messages.

```bash
uv run glc token
curl -X POST http://localhost:8111/v1/control/pair \
  -H "Authorization: Bearer <your-token>"
```

Send the 6-digit code from your WhatsApp to the sandbox number to complete pairing.

### Step 8 — Send your first message

Send any message from your personal WhatsApp to the sandbox number. The agent will reply through Twilio.

![User initiated message](assets/screenshots/twilio_05_user_initiated_message.png)

---

## Provider Routing

When the agent sends a reply, the gateway picks the provider as follows:

1. **Cached provider** — if your number sent an inbound message recently, the same provider is used for the reply. This is the common case and requires no extra API calls.
2. **Meta first** — if there is no cached provider, the gateway tries Meta. On success, it caches `meta` for your number.
3. **Automatic Twilio fallback** — if Meta returns error `131030` (recipient phone number not in Meta's allowed list — a test account restriction only), the gateway automatically retries via Twilio and caches `twilio` for your number going forward.

Error `131047` (24-hour re-engagement window closed) is **not** a Twilio-fallback case — the gateway returns the error as-is, and you must re-initiate the conversation from your phone first (see [Troubleshooting](#troubleshooting)).

Replies are only sent to paired recipients (`owner_paired` or `user_paired`). Messages from unpaired numbers are silently dropped before any provider send is attempted.

The provider cache is in-memory only and resets when the gateway restarts.

---

## Known Limitations

**Webhook verification mechanism:** When you click "Verify and Save" in the Meta console (Step 12), Meta sends a one-time GET request containing a `hub.challenge` value. The gateway must echo that value back exactly for verification to succeed — this is the mechanism behind "verification completes automatically."

**No group chat or @mention support:** Neither Meta's Cloud API nor Twilio's WhatsApp integration supports group chats or @mentions the way Slack or Discord do. The `is_public_channel` and `was_mentioned` fields in the shared allowlist contract exist for other channels — for WhatsApp every conversation is effectively a DM, so these are always treated as direct messages.

**Test account vs. production:**

| | Test / Sandbox (this guide) | Production |
|---|---|---|
| Meta | Shared test number from the Meta dashboard — only phone numbers explicitly added there can receive messages. The 24-hour window must be reopened manually by sending the template message first. The access token expires in 24 hours unless exchanged for a 60-day token (Step 9). | Dedicated, verified WABA number. Any number can be messaged within Meta's policies. The same 24-hour window rules apply, but token management is handled via system users. |
| Twilio | Shared sandbox number (`+14155238886`) — every recipient must opt in with a join code that expires every 3 days (error `63016`). | Dedicated Twilio number. No opt-in / join code required. |

**Setup time:** Budget 30–60 minutes per provider for a first-time setup. Between app creation, credential collection, tunnel setup, webhook registration, and phone pairing, there are several dashboard steps with no shortcuts.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No reply after sending a message | Phone not paired | Run the pairing flow — see Step 13 (Meta) or Step 7 (Twilio) |
| Meta error `131047` | 24-hour re-engagement window closed | Send a message to your test number from your phone first to reopen it |
| Meta error `190` | Access token expired | Regenerate the token from the Meta "Step 1. Try it out" panel and update `WHATSAPP_TOKEN` |
| Twilio error `63016` | Sandbox join code expired | Re-send `join <code>` from your personal WhatsApp to the sandbox number |
| Webhook verification fails (Meta) | Verify token mismatch | Ensure `WHATSAPP_VERIFY_TOKEN` in `.env` exactly matches what is entered in the Meta console |
| Twilio signature validation fails | `TWILIO_WEBHOOK_URL` mismatch | Ensure `TWILIO_WEBHOOK_URL` exactly matches the URL saved in Twilio Sandbox Settings |
| Gateway not receiving messages | Tunnel not running or wrong port | Confirm your tunnel is running and pointing to port 8111 |
| `outbound_blocked` error | Recipient not paired | Pair the number first via `/v1/control/pair` |
| Messages delivered to Meta but not Twilio | Sandbox join expired | Re-join the Twilio sandbox with the join code |
| Gateway starts but channel not found | Adapter registration failed | Check `uv run glc serve` output for import errors in `adapter.py` |

---

## Project Structure

```
glc/channels/catalogue/whatsapp/
├── adapter.py              ← all inbound and outbound logic for both providers
├── schemas.py              ← optional typed wrappers (currently unused)
├── assets/
│   └── screenshots/        ← screenshots used in this README
│       ├── meta_01_app_details.png
│       ├── meta_02_use_cases.png
│       ├── ...
│       ├── twilio_01_choose_plan.png
│       ├── twilio_02_account_credentials.png
│       └── ...
└── tests/
    └── test_twilio_path.py
```

The adapter depends on these shared modules (outside this folder):

| File | Purpose |
|---|---|
| `glc/channels/base.py` | Abstract base class all channel adapters implement |
| `glc/channels/envelope.py` | `ChannelMessage` and `ChannelReply` — the shared message contract |
| `glc/security/trust_level.py` | Classifies each sender as `owner_paired`, `user_paired`, or `untrusted` |
| `glc/security/allowlists.py` | Decides whether a sender is allowed to interact |
| `glc/security/pairing.py` | Pairing store — tracks which phone numbers are registered |
