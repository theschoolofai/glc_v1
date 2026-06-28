# WhatsApp (Meta Cloud API or Twilio Sandbox)

This is a **group assignment** in Session 11. Implement the whatsapp adapter
to make the test suite at `tests/channels/test_whatsapp.py` pass.

## What you build

Two files under this directory:

- `adapter.py` — subclass `glc.channels.base.ChannelAdapter` and implement
  `on_message(raw) -> ChannelMessage` and `send(reply) -> Any`.
- `schemas.py` — any channel-specific Pydantic types you need.

## Required environment variables

Meta Cloud API:
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_TOKEN`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_WABA_ID`
- `WHATSAPP_APP_ID`

Twilio Sandbox:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_WHATSAPP_FROM`
- `TWILIO_WEBHOOK_URL`

Never commit real values — store them in a local `.env` file (already gitignored).

## Free-tier limits

Meta WhatsApp Cloud API allows 1,000 free service conversations per month.

## Wire-format quirks to expect

24-hour session window: outside it, only approved templated messages are deliverable. Webhook verification handshake uses a hub.challenge echo.

## Tests you need to pass

The failing tests live at `tests/channels/test_whatsapp.py`. They cover:

1. `on_message` builds a valid `ChannelMessage` for owner and stranger inputs.
2. Trust level resolves to `owner_paired` / `user_paired` / `untrusted` correctly.
3. `send` produces a valid wire-format payload and reaches the mock.
4. The adapter handles forced disconnects without raising.
5. Rate-limit responses propagate to the caller as a 429.
6. In public channels with the default `mention_only_in_public: true`, the
   adapter consults the allowlist before processing strangers.

The mock-API fake at `tests/channels/mocks/whatsapp_mock.py` is your contract
surface. Do **not** edit the mock or the test file — they are fixed.

## Outbound policy

The WhatsApp `send()` path is a dual-provider orchestrator. It uses the last
verified inbound provider for a recipient when available, otherwise it tries
Meta Cloud API first and falls back to Twilio Sandbox only when Meta returns
error code `131030`.

Outbound replies are allowed for any paired recipient:

- `owner_paired`
- `user_paired`

Unpaired recipients are blocked before any provider send attempt.

The provider cache is process-local and in memory only. It is intentionally
not persisted across restarts.

For real runtime use, enable `whatsapp` in your active `channels.yaml`.
The packaged scaffold defaults most channels to disabled, and the fixed
adapter tests exercise `on_message()` directly rather than the full gateway
allowlist path.

## Submission

Open a PR that:

- Adds your `adapter.py` and `schemas.py`.
- Passes `pytest tests/channels/test_whatsapp.py`.
- Updates `CLAIMS.md` if you have not already claimed this channel.

CI gates merge through branch protection. A TA reviews before merge.
