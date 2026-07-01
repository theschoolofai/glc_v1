# Team LINE Setup Guide

This guide is for teammates who are starting from zero: no existing LINE app
account, no LINE Official Account, and no Messaging API credentials.

The goal is to create your own LINE bot, generate your own `.env` credentials,
capture your real LINE owner `source.userId`, and verify the bot reaches the
GLC LINE bridge as `owner_paired`.

## What You Will Create

- A personal LINE account, used to log in and test from the LINE app.
- A LINE Official Account, which users add as a friend.
- A LINE Messaging API channel, linked to that Official Account.
- A local untracked `.env` file with:
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_CHANNEL_SECRET`
  - `LINE_OWNER_USER_ID`

Do not commit `.env`, tokens, channel secrets, screenshots of secrets, or copied
credentials.

## 1. Create The LINE Account And Official Account

1. Install the LINE app on your phone or desktop.
2. Create a new LINE user account and confirm you can send messages from it.
3. Open LINE Official Account Manager:
   `https://manager.line.biz/`
4. Sign in with the same LINE account.
5. Create a new Official Account for your bot.
6. Note the bot's Basic ID, such as `@123abcde`.

The Basic ID is useful for adding the bot as a friend, but it is not your
`LINE_OWNER_USER_ID`.

## 2. Enable Messaging API

1. In LINE Official Account Manager, open your bot account.
2. Go to `Settings` -> `Messaging API`.
3. Click `Enable Messaging API`.
4. Select an existing LINE Developers provider or create a new provider.
5. Read the provider warning carefully.

Once a LINE Official Account is linked to a provider, LINE warns that the
provider cannot be changed or unlinked. Use the provider you want this bot to
belong to long term.

If LINE asks for Privacy Policy and Terms of Use URLs, they can be left blank
for this assignment flow unless your team requires them.

## 3. Generate LINE Credentials

After Messaging API is enabled, the Official Account Manager shows channel
information.

Copy these values into your local `.env` only:

- `Channel secret` -> `LINE_CHANNEL_SECRET`
- `Channel access token (long-lived)` -> `LINE_CHANNEL_ACCESS_TOKEN`

The long-lived access token is usually issued from LINE Developers Console:

1. Open LINE Developers Console:
   `https://developers.line.biz/console`
2. Select your provider.
3. Select your Messaging API channel.
4. Open the `Messaging API` tab.
5. Under `Channel access token`, click `Issue`.
6. Copy the token into `.env`.

Never paste the token or secret into chat, PRs, docs, terminal logs, or slides.

## 4. Create Your Local `.env`

From the `glc_v1` repo root:

```bash
cd /Users/pravingadekar/Documents/EAG3/EAG3-11/glc_v1
cp glc/channels/catalogue/line/line.env.example .env
```

Edit `.env` and set the LINE values:

```bash
LINE_CHANNEL_ACCESS_TOKEN=replace-with-your-long-lived-channel-access-token
LINE_CHANNEL_SECRET=replace-with-your-channel-secret
LINE_OWNER_USER_ID=replace-after-webhook-capture
```

Leave `LINE_OWNER_USER_ID` as a placeholder until you capture it from a real
inbound webhook. It is not available from the account profile page.

Confirm the values are present without printing secrets:

```bash
awk -F= '/^LINE_CHANNEL_ACCESS_TOKEN=/ {print "LINE_CHANNEL_ACCESS_TOKEN=" (length($2) ? "set" : "empty")}
/^LINE_CHANNEL_SECRET=/ {print "LINE_CHANNEL_SECRET=" (length($2) ? "set" : "empty")}
/^LINE_OWNER_USER_ID=/ {print "LINE_OWNER_USER_ID=" (length($2) ? "set" : "empty")}' .env
```

Validate the token with a read-only LINE API call:

```bash
set -a
source .env
set +a

curl -fsS -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" \
  https://api.line.me/v2/bot/info
```

Expected: JSON containing your bot `displayName`, `basicId`, and bot `userId`.

Do not copy the returned bot `userId` into `LINE_OWNER_USER_ID`. That value is
the bot's id, not your human LINE user id.

## 5. Start The Local Services

Use four terminals for the live flow.

Terminal 1: start the GLC gateway.

```bash
cd /Users/pravingadekar/Documents/EAG3/EAG3-11
./start_glc_gateway.sh
```

Terminal 2: start the EAG3-09 agent wrapper.

```bash
cd /Users/pravingadekar/Documents/EAG3/EAG3-11/EAG3-09/code
PYTHONPATH=/Users/pravingadekar/Documents/EAG3/EAG3-11/glc_v1 \
  uv run uvicorn glc.channels.catalogue.line.agent_service:app \
  --host 127.0.0.1 --port 8200
```

Optional health check:

```bash
curl -s http://127.0.0.1:8200/health
```

Terminal 3: start the LINE bridge.

```bash
cd /Users/pravingadekar/Documents/EAG3/EAG3-11/glc_v1
set -a
source .env
set +a
export GLC_PAIRING_DB="$HOME/.glc/line-pairings.sqlite"
export AGENT_URL=http://127.0.0.1:8200/agent/query

uv run uvicorn glc.channels.catalogue.line.live_bridge:app \
  --host 127.0.0.1 --port 8123
```

Optional bridge health check:

```bash
curl -s http://127.0.0.1:8123/health
```

Expected: `"ok": true` and `"line_configured": true`.

Terminal 4: expose the bridge over HTTPS.

```bash
cd /Users/pravingadekar/Documents/EAG3/EAG3-11/glc_v1
npx --yes localtunnel --port 8123
```

Copy the printed HTTPS URL. Your webhook URL is:

```text
https://<your-tunnel-host>/callback
```

## 6. Configure The LINE Webhook

In LINE Developers Console for your Messaging API channel:

1. Open the `Messaging API` tab.
2. Set `Webhook URL` to `https://<your-tunnel-host>/callback`.
3. Click `Update` or `Save`.
4. Click `Verify`.
5. Turn `Use webhook` on.

If the LINE API or console shows the endpoint but `active=false`, use the
console UI switch. In practice, the `Use webhook` UI toggle is the reliable
source of truth.

Recommended cleanup for cleaner demos:

- Disable default auto-reply messages.
- Disable greeting messages if they clutter your recording.

Those built-in LINE messages can appear as:

```text
Thanks for your message!
Unfortunately, this account isn't set up to reply directly to messages.
```

They are from LINE Official Account features, not from the GLC adapter.

## 7. Capture Your Real Owner User ID

Add your Official Account as a friend from the same LINE account you want to use
as owner. You can usually use:

```text
https://line.me/R/ti/p/<your-basic-id>
```

For example, if the Basic ID is `@123abcde`:

```text
https://line.me/R/ti/p/@123abcde
```

Send any simple message from the LINE app, such as:

```text
hello
```

Terminal 3 should log something like:

```text
[line] inbound user_id=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx trust=untrusted text='hello'
[line] outbound endpoint=/reply status=200
```

Copy the exact `U...` value from `user_id=...`. That is the value for
`LINE_OWNER_USER_ID`.

Do not use any of these as `LINE_OWNER_USER_ID`:

- Bot Basic ID, such as `@123abcde`
- Bot `userId` returned by `/v2/bot/info`
- Human-readable LINE handle
- LINE Manager chat UI ids
- Message ids

## 8. Update `.env` And Pair The Owner

Edit `.env`:

```bash
LINE_OWNER_USER_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Then pair the owner using the same persistent pairing DB used by the bridge:

```bash
cd /Users/pravingadekar/Documents/EAG3/EAG3-11/glc_v1
set -a
source .env
set +a
export GLC_PAIRING_DB="$HOME/.glc/line-pairings.sqlite"

uv run python -c 'from glc.security.pairing import get_pairing_store
import os
user_id = os.environ["LINE_OWNER_USER_ID"]
get_pairing_store().force_pair_owner("line", user_id, user_handle="owner")
print("paired line owner")'
```

Verify local trust classification:

```bash
set -a
source .env
set +a
export GLC_PAIRING_DB="$HOME/.glc/line-pairings.sqlite"

uv run python -c 'from glc.security.trust_level import classify
import os
print(classify("line", os.environ["LINE_OWNER_USER_ID"]))'
```

Expected:

```text
owner_paired
```

If the bridge was running with a temporary `GLC_PAIRING_DB`, stop it and restart
it with:

```bash
export GLC_PAIRING_DB="$HOME/.glc/line-pairings.sqlite"
```

## 9. Verify End To End

Send a real question from the LINE app:

```text
Who wrote Dune and when was it first published? Answer in one sentence.
```

Expected in LINE:

1. Immediate acknowledgement:

   ```text
   Got it. I am working on your answer.
   ```

2. Final answer from the EAG3-09 agent, for example:

   ```text
   The science fiction novel Dune was written by Frank Herbert and was first published in 1965.
   ```

Expected in Terminal 3:

```text
[line] inbound user_id=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx trust=owner_paired text='...'
[line] outbound endpoint=/reply status=200
[line] outbound endpoint=/push status=200
```

The first outbound uses LINE's one-shot reply token. The later answer uses push.
That reply-then-push behavior is expected.

## Troubleshooting

### LINE says "This LINE account is not paired"

The webhook is working, but the incoming `source.userId` is not paired.

Fix:

1. Copy the `user_id=U...` value from the bridge log.
2. Put it in `LINE_OWNER_USER_ID`.
3. Run the pairing command with the same `GLC_PAIRING_DB` used by the bridge.
4. Restart the bridge if it was using the wrong pairing DB.

### LINE says "Got it" and then "agent unavailable"

LINE is working and the owner is paired, but the EAG3-09 agent wrapper is not
reachable on `127.0.0.1:8200`.

Fix:

```bash
curl -s http://127.0.0.1:8200/health
```

If that fails, restart Terminal 2.

### LINE receives nothing

Check these in order:

1. Terminal 3 bridge is running on `:8123`.
2. Terminal 4 tunnel is still running.
3. Webhook URL ends in `/callback`.
4. `Use webhook` is on in LINE Developers Console.
5. `curl -s http://127.0.0.1:8123/health` returns `"line_configured": true`.

### The console shows `active=false`

Use the LINE Developers Console UI and manually toggle `Use webhook` on. The API
can accept the endpoint URL while the UI switch remains off.

### You see duplicate default LINE messages

Disable auto-reply messages and greeting messages in LINE Official Account
Manager response settings. Those messages are separate from the GLC bridge.

## Shutdown

When you are done with a live test:

1. Stop the tunnel with `Ctrl-C`.
2. Stop the LINE bridge with `Ctrl-C`.
3. Stop the agent wrapper and gateway if no longer needed.
4. Turn `Use webhook` off in LINE Developers Console if you do not want future
   LINE messages delivered to your local machine.

Localtunnel URLs are temporary. The next session usually needs a fresh tunnel
URL and an updated LINE webhook URL.
