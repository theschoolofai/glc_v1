# LINE Messaging API

This is a **group assignment** in Session 11. Implement the line adapter
to make the test suite at `tests/channels/test_line.py` pass.

## What you build

Two files under this directory:

- `adapter.py` — subclass `glc.channels.base.ChannelAdapter` and implement
  `on_message(raw) -> ChannelMessage` and `send(reply) -> Any`.
- `schemas.py` — any channel-specific Pydantic types you need.

## Required environment variables

- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_CHANNEL_SECRET`

## Free-tier limits

Developer trial: 500 free push messages/month; reply messages within the 1-hour reply token are unlimited.

## Wire-format quirks to expect

Reply tokens are one-shot and expire fast — push messages cost against the monthly quota. Signed webhook validation uses the channel secret.

## Tests you need to pass

The failing tests live at `tests/channels/test_line.py`. They cover:

1. `on_message` builds a valid `ChannelMessage` for owner and stranger inputs.
2. Trust level resolves to `owner_paired` / `user_paired` / `untrusted` correctly.
3. `send` produces a valid wire-format payload and reaches the mock.
4. The adapter handles forced disconnects without raising.
5. Rate-limit responses propagate to the caller as a 429.
6. In public channels with the default `mention_only_in_public: true`, the
   adapter consults the allowlist before processing strangers.

The mock-API fake at `tests/channels/mocks/line_mock.py` is your contract
surface. Do **not** edit the mock or the test file — they are fixed.

## Reusing this adapter outside the test harness

`adapter.py` is a **wire-format translator only** — it is not a standalone LINE
bot. To run a real bot you must supply three things around it:

| Responsibility | What you provide |
| --- | --- |
| Webhook server  | An HTTP endpoint that receives LINE's POSTs and calls `Adapter.on_message(raw)`. |
| Signature check | Verify the `X-Line-Signature` header (HMAC-SHA256 over the raw body with the channel secret, base64) **before** trusting the payload. |
| Transport       | An object satisfying the `LineTransport` Protocol, injected via `config={"transport": ...}` (the `"mock"` key is a back-compat alias). |

The `LineTransport` contract (defined in `adapter.py`):

- **Required:** `async send(payload)` and `consume_reply_token(user_id)`.
- **Recommended:** `set_reply_token(user_id, token, ttl_s=60.0)` — omit it and
  the adapter keeps a one-shot local cache so the first reply after each
  inbound still uses LINE's quota-free reply endpoint — and `pop_disconnect()`.

A complete, working reference for all three lives in `dev/live_bridge.py`:
`RealLineTransport` (real `httpx` calls to `api.line.me`), `verify_line_signature`,
and `BridgeConfig.from_env` (loads `LINE_CHANNEL_ACCESS_TOKEN` /
`LINE_CHANNEL_SECRET`).

## Submission

Open a PR that:

- Adds your `adapter.py` and `schemas.py`.
- Passes `pytest tests/channels/test_line.py`.
- Updates `CLAIMS.md` if you have not already claimed this channel.

CI gates merge through branch protection. A TA reviews before merge.
