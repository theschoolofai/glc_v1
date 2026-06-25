# Twilio SMS Adapter — GLC v1

## Architecture

```
Inbound (Twilio webhook)            Outbound (ChannelReply)
------------------------            ----------------------
application/x-www-form-urlencoded   Twilio messages.create
       |                                       |
       v                                       v
  Adapter.on_message()                  Adapter.send()
       |                                       |
       v                                       v
  ChannelMessage (canonical)           Twilio wire payload
       |                                       |
       +------+       +------+
              |       |
              v       v
         Gateway runtime / Agent
```

### Inbound path

1. Twilio POSTs a webhook with form fields (`From`, `To`, `Body`,
   `NumMedia`, `MediaUrl0..N`, `MessageSid`, `AccountSid`).
2. `on_message` parses the raw dict, teaches itself the bot's phone via
   `To` (first inbound only), and classifies trust with
   `glc.security.trust_level.classify`.
3. MMS media is downloaded through the mock transport (`mock.download`)
   or, in live mode, via HTTP Basic Auth using `TWILIO_ACCOUNT_SID` /
   `TWILIO_AUTH_TOKEN`.
4. Bytes are SHA-256 hashed and stored in the artifact store; an
   `Attachment` with `ref="art:<sha>"` is attached to the envelope.
5. A `ChannelMessage` is returned with `trust_level` already resolved,
   so the runtime never touches raw Twilio metadata again.

### Outbound path

1. The gateway returns a `ChannelReply` with optional image attachments.
2. `send` builds a form payload with capitalised Twilio keys: `From`,
   `To`, `Body`.
3. If an image attachment is present, its `metadata["public_url"]` is
   promoted to `MediaUrl` so Twilio fetches the bytes from the public
   artifact endpoint.
4. In tests the mock receives the dict via `await mock.send(...)`; in
   production the adapter POSTs to Twilio's REST endpoint with Basic
   Auth and parses the JSON response.

### Trust boundary

| Scenario | Trust level | Mechanism |
|----------|-------------|-----------|
| Owner-paired sender | `owner_paired` | Pairing store entry created by `test fixture` |
| Unknown sender | `untrusted` | `classify()` falls back when no pairing exists |
| Public channel + non-owner | `untrusted` (dropped) | `glc.security.allowlists.allowed` gate |

The adapter is deliberately *read-only* for inbound trust: it never
writes to the pairing store itself — that is controlled exclusively by
the owner-pairing workflow outside the channel layer. This matches the
GLC v1 mandate that the LLM can *read* trust classifications but cannot
*promote* its own trust level.

## Channel quirks

- Twilio uses `application/x-www-form-urlencoded`, NOT JSON. Keys are
  capitalised (`From`, `To`, `Body`); lowercase keys are silently
  accepted by Twilio's API but tests enforce the canonical caps.
- MMS media arrives as `NumMedia` + parallel arrays `MediaUrl0..N`,
  `MediaContentType0..N`. Only `MediaUrl0` is needed for a single
  attachment.
- Phone numbers are the durable channel user IDs. No username/handle
  abstraction exists unless the agent explicitly maps one in memory.
- Rate-limited Twilio responses return JSON with `status: 429` and
  `code: 20429`; `send` propagates this dict unchanged so the runtime
  can back-off.

## Running tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest tests/channels/test_twilio_sms.py -v
```

## CI quality gates

- `ruff check` — zero style errors
- `mypy` — strict type validation passes
- `pytest` — 8 tests, including trust-boundary adversarial scenarios
- Bidirectional translation validated: wire → canonical (`on_message`)
  and canonical → wire (`send`)
- Mock-API smoke test runs against `tests/channels/mocks/twilio_sms_mock.py`