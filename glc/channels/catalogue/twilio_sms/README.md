# Twilio SMS Adapter — GLC v1

## Module map

| File | Role |
|------|------|
| `adapter.py` | `Adapter.on_message` (wire → `ChannelMessage`) and `Adapter.send` (`ChannelReply` → wire). The only file the test suite and `registry.discover()` import. |
| `schemas.py` | Typed Twilio wire models (`TwilioInboundForm`, `TwilioMediaItem`, `TwilioSendPayload`) and the artifact metadata sidecar (`StoredArtifact`). |
| `artifacts.py` | Content-addressed store for inbound MMS bytes (`put`/`get_bytes`/`get_meta`/`get_path`/`exists`/`remove`/`cleanup_expired`), keyed by sha256, under `~/.glc/artifacts` or `$GLC_ARTIFACTS_DIR`. |
| `webhook.py` | Production HTTP receiver (`build_app`) that verifies `X-Twilio-Signature`, serves stored artifacts back to Twilio, and bridges to the GLC gateway over WebSocket (`gateway_roundtrip`). |
| `server.py` | The runnable live demo process — pairs the owner, boots the webhook receiver, and prints each hop of a real SMS/MMS round-trip. See **Live Demo** below. |

## Architecture

```
                    Test / CI path                          Live path
                    ---------------                          ---------
              Adapter(config={"mock": m})           Twilio webhook (form-urlencoded)
                          |                                       |
                          |                                       v
                          |                            webhook.py: verify X-Twilio-Signature
                          |                                       |
                          v                                       v
                   Adapter.on_message()  <----------------------+
                          |
                          v
                  ChannelMessage (canonical, trust_level resolved)
                          |
              +-----------+-----------+
              |                       |
      test asserts fields     server.py: gateway_roundtrip()
                               (WS client -> GLC gateway :8111,
                                /v1/channels/twilio_sms ->
                                allowlist/rate-limit/audit/echo)
                                       |
                                       v
                               ChannelReply (from gateway or test)
                                       |
                                       v
                               Adapter.send()
                                       |
                          +------------+------------+
                          |                         |
                 mock.send(payload)         POST Messages.json (live)
                 (tests/CI)                 Basic Auth, graceful 429
```

Two inbound entry points exist by design: the **mock** path (`Adapter(config={"mock": ...})`)
is what CI exercises against `tests/channels/mocks/twilio_sms_mock.py`; the **live** path
(`webhook.py` → `on_message` → a real WebSocket round-trip to the GLC gateway → `send`) is
what a real Twilio number drives in production. `server.py` is the process that wires the
live path together end to end — see **Live Demo**.

### Inbound path

1. Twilio POSTs a webhook with form fields (`From`, `To`, `Body`,
   `NumMedia`, `MediaUrl0..N`, `MediaContentType0..N`, `MessageSid`, `AccountSid`). In
   production this arrives at `webhook.py`, which verifies `X-Twilio-Signature` *before*
   the payload is trusted (see Channel quirks) and parses the body with `urllib.parse.parse_qsl`
   (no `python-multipart` dependency needed).
2. `on_message` parses the raw dict via `TwilioInboundForm.from_raw` (tolerant — never raises,
   even on malformed input), teaches itself the bot's phone via `To` (first inbound only), and
   classifies trust with `glc.security.trust_level.classify`.
3. `Body` is checked against carrier opt-out/help keywords (`STOP`/`STOPALL`/`UNSUBSCRIBE`/
   `CANCEL`/`END`/`QUIT`, `START`/`YES`/`UNSTOP`, `HELP`/`INFO`, case-insensitive); a match is
   surfaced as `metadata["sms_keyword"]` so the runtime can honor compliance without the
   adapter itself deciding policy.
4. MMS media (`form.media_items()`) is downloaded through the mock transport
   (`mock.download`) in tests, or via HTTP Basic Auth using `TWILIO_ACCOUNT_SID` /
   `TWILIO_AUTH_TOKEN` in live mode.
5. Bytes are SHA-256 hashed and **persisted** — in tests via `mock.store_artifact`, in
   production via the local `artifacts.put()` store (dedup by content hash, typed `.json`
   metadata sidecar). An `Attachment` with `ref="art:<sha>"` and a kind derived from the MIME
   type (`image/*` → `image`, `audio/*` → `audio`, `video/*` → `video`, else `file`) is
   attached to the envelope.
6. A `ChannelMessage` is returned with `trust_level` already resolved, so the runtime never
   touches raw Twilio metadata again.

### Outbound path

1. The gateway (or, in tests, the test itself) returns a `ChannelReply` with optional image
   attachments.
2. `send` builds a form payload with capitalised Twilio keys: `From`, `To`, `Body`.
3. For each image attachment, the adapter resolves a public URL Twilio can fetch, in order:
   `metadata["public_url"]` → a plain `http(s)://` value already in `ref` → an `art:<sha>` ref
   resolved against `config["artifact_public_base"]` / `GLC_ARTIFACT_PUBLIC_BASE` (e.g. the
   `webhook.py` `/artifacts/<sha>` route behind an ngrok tunnel). Anything unresolvable is
   **not silently dropped** — it's recorded under `skipped_media` in the returned/send result.
   Single image → `MediaUrl`; multiple → a list.
4. In tests the mock receives the dict via `await mock.send(...)`; in production the adapter
   POSTs to Twilio's REST endpoint with Basic Auth. A non-2xx response (e.g. a 429 rate limit)
   is **not raised** — it's returned as Twilio's error JSON dict (`code`, `status`, and
   `retry_after` when present), matching the mock's contract so callers handle both uniformly.

### Trust boundary

| Scenario | Trust level | Mechanism |
|----------|-------------|-----------|
| Owner-paired sender | `owner_paired` | Pairing store entry created by `force_pair_owner()` — the test fixture in CI, the live runner (`server.py`) in production (see Live Demo) |
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
  `MediaContentType0..N`. Any number of items are supported via
  `TwilioInboundForm.media_items()`, not just a single attachment.
- Phone numbers are the durable channel user IDs. No username/handle
  abstraction exists unless the agent explicitly maps one in memory.
- Rate-limited Twilio responses return JSON with `status: 429` and
  `code: 20429`; `send` propagates this dict unchanged (never raises) so the runtime
  can back off.
- Every inbound webhook is signed: `X-Twilio-Signature` is
  `base64(HMAC-SHA1(auth_token, url + concat(sorted POST params)))`. `webhook.py` verifies
  this before `on_message` ever sees a payload — without it, anyone could POST a forged
  webhook spoofing the owner's number and be classified `owner_paired`. `GLC_TWILIO_SKIP_SIG=1`
  bypasses verification for local dev only; never set it in a real deployment.

## Live Demo

An end-to-end demo — a real SMS/MMS from a phone is echoed back through the GLC gateway
over a real WebSocket:

```
Phone ──SMS──▶ Twilio ──POST──▶ server.py (webhook) ──on_message──▶ ChannelMessage
  ▲              ▲                      │ verify X-Twilio-Signature
  │ reply SMS    │ messages.json        ▼
  │              └───────────── adapter.send ◀── ChannelReply ◀── WS ── GLC gateway :8111
  └────────────────────────────────────────────────────────────         (allowlist→rate-limit→audit→echo)
```

### Components

| # | Component | Command | Role |
|---|-----------|---------|------|
| 1 | **GLC gateway** | `uv run glc serve` | WS server `/v1/channels/twilio_sms`, pairing, allowlist, rate-limit, audit, stub echo |
| 2 | **Runner** (`server.py`) | `python -m glc.channels.catalogue.twilio_sms.server` | Receives Twilio POST → `on_message` → WS client to gateway → `adapter.send` |
| 3 | **ngrok** | `ngrok http 8200` | Public HTTPS URL so Twilio can reach the runner |
| — | **Twilio + phone** | — | Your number; webhook points at the ngrok URL |

### Prerequisites

- A Twilio account, a Twilio phone number, and (trial) a verified destination number.
- `ngrok` installed and authed (`ngrok config add-authtoken ...`).
- `.env` in `glc_v1/`:
  ```
  TWILIO_ACCOUNT_SID=ACxxxxxxxx
  TWILIO_AUTH_TOKEN=xxxxxxxx
  TWILIO_PHONE_NUMBER=+1500...      # your Twilio number (outbound From)
  TWILIO_OWNER_NUMBER=+1XXXXXXXXXX  # your mobile (paired as owner)
  ```

### Steps

1. **Gateway** — terminal A:
   ```bash
   cd glc_v1
   uv run glc serve            # http://localhost:8111
   ```
2. **Tunnel** — terminal B:
   ```bash
   ngrok http 8200             # copy the https://<id>.ngrok-free.app URL
   ```
3. **Runner** — terminal C:
   ```bash
   cd glc_v1
   GLC_PUBLIC_BASE=https://<id>.ngrok-free.app \
     uv run python -m glc.channels.catalogue.twilio_sms.server
   ```
   It pairs your owner number, serves the webhook on `:8200`, and serves
   `/artifacts/<sha>` for outbound MMS.
4. **Twilio console** → Phone Numbers → your number → *A MESSAGE COMES IN*:
   set to `https://<id>.ngrok-free.app/webhooks/twilio_sms`, method **HTTP POST**, Save.
5. **Text your Twilio number** from your phone. Terminal C shows: signature OK →
   `ChannelMessage` (trust=`owner_paired`) → WS send → gateway `[glc echo] ...` →
   `adapter.send` → a reply SMS lands on your phone.
6. **MMS take** — text a photo. The console shows the media downloaded, hashed, and
   persisted as `art:<sha>`. The echo reply can carry it back as
   `https://<id>.ngrok-free.app/artifacts/<sha>`.

### Dry-run without a phone (optional)

Skip signature verification and POST a sample form locally:
```bash
GLC_TWILIO_SKIP_SIG=1 uv run python -m glc.channels.catalogue.twilio_sms.server &
curl -X POST http://localhost:8200/webhooks/twilio_sms \
  -d 'From=+1XXXXXXXXXX' -d 'To=+1500...' -d 'Body=hello' -d 'NumMedia=0'
```
(The gateway on `:8111` must still be running for the WS hop.)

### Troubleshooting

- **403 invalid signature** — the URL Twilio signed must match `request.url`. Behind ngrok
  use the exact `https` forwarded URL; as a last resort set `GLC_TWILIO_SKIP_SIG=1` (dev only).
- **gateway unreachable** — start `uv run glc serve` (terminal A); check `GLC_GATEWAY_PORT`.
- **reply not delivered** — on a Twilio trial the destination must be a *verified* number;
  check `TWILIO_PHONE_NUMBER` is your real Twilio From.
- **owner shows untrusted** — set `TWILIO_OWNER_NUMBER` to the exact E.164 number you text from.

## Running tests

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest tests/channels/test_twilio_sms.py glc/channels/catalogue/twilio_sms/tests/ -v
```

## CI quality gates

- `ruff check glc/channels/catalogue/twilio_sms/` — zero style errors
- `mypy glc/channels/catalogue/twilio_sms/` — strict type validation passes
- `pytest` — 54 tests total: the 7 fixed contract tests, plus dedicated modules for the
  artifact store, live (non-mock) paths, signature verification, wire/envelope behaviors,
  webhook routing, and the original multi-MMS scenario
- Bidirectional translation validated: wire → canonical (`on_message`)
  and canonical → wire (`send`)
- Mock-API smoke test runs against `tests/channels/mocks/twilio_sms_mock.py`
