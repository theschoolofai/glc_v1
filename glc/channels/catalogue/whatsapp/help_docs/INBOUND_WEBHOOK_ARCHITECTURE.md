# Inbound Webhook Architecture — WhatsApp Adapter

**Scope:** This document explains how inbound WhatsApp messages reach `adapter.py`,
covering three approaches — Dev/POC, Demo (US-13), and the Standardized production
pattern. It also explains why outbound (sending) needs none of this.

---

## The core distinction: Sending vs. Receiving

### Sending (outbound) — already works, no webhook server needed

`adapter.send()` initiates the call. It builds the provider payload and POSTs directly
to Meta/Twilio's API. The GLC gateway or demo script calls it explicitly.

```
adapter.send(ChannelReply)
    │
    ├── build_meta_send_payload()          glc/channels/catalogue/whatsapp/adapter.py
    │   POST https://graph.facebook.com/…/messages
    │
    └── build_twilio_send_payload()        glc/channels/catalogue/whatsapp/adapter.py
        POST https://api.twilio.com/…/Messages.json
```

**No webhook server. No tunnel. Already green after US-5 and US-8.**

---

### Receiving (inbound) — requires something to accept Meta/Twilio's HTTP POST

Meta and Twilio are third-party platforms. They fire an **HTTP POST** to a URL you
register in their console. They cannot use WebSocket. They cannot send `ChannelMessage`
— they always send their own fixed wire formats:

| Provider | Method | Content-Type | Shape |
|---|---|---|---|
| Meta | HTTP POST | `application/json` | `{"object":"whatsapp_business_account","entry":[…]}` |
| Twilio | HTTP POST | `application/x-www-form-urlencoded` | `WaId=…&Body=…&From=…&MessageSid=…` |

Something must sit at a public URL, receive these POSTs, and hand them to
`adapter.on_message()`. **That is the gap this document addresses.**

---

## Why `/v1/channels/whatsapp` cannot receive webhooks directly

`glc/routes/channels.py` exposes:

```python
@router.websocket("/v1/channels/{name}")   # line 31
```

This is a **WebSocket** endpoint — Meta/Twilio only support HTTP POST. You cannot
register a WebSocket URL in Meta or Twilio's console. WebSocket is a persistent
two-way connection that the adapter initiates; Meta/Twilio's webhook system is
fire-and-forget HTTP that they initiate.

---

## Three approaches

---

### Approach 1 — Dev / POC (US-1 era)

**Purpose:** Verify that Meta webhook registration works. Does NOT involve `adapter.py`.

**Startup sequence (3 terminals):**

```
Terminal 1                              Terminal 2                Meta Console
─────────────────────────────           ──────────────            ─────────────────
uv run python                           ngrok http 8765           Webhook URL:
  .../US1_meta_wiring/scripts/                                    https://abc.ngrok.app/
  meta_webhook_test_server.py           → prints public URL       Verify Token:
                                                                  glc-verify-token-us1
Listens on :8765
```

**Flow:**

```
Your Phone
    │ sends WhatsApp message
    ▼
Meta Cloud API
    │ POST https://abc.ngrok.app/
    │ X-Hub-Signature-256: sha256=…
    │ Body: {"entry":[…]}
    ▼
ngrok tunnel
    │ forwards to localhost:8765
    ▼
meta_webhook_test_server.py            ← US1_meta_wiring/scripts/meta_webhook_test_server.py
    │ verifies HMAC signature
    │ prints raw JSON to console
    │
    ✗ STOPS HERE
    ✗ adapter.on_message() never called
    ✗ no reply sent to phone
```

**Limitation:** Proves the pipe exists. Adapter logic is untouched.

---

### Approach 2 — Our Demo Approach (US-13)

**Relationship to backlog B2:** Approach 3 (`POST /v1/channels/{name}/webhook` in
`channels.py`) is the more evolved and correct solution compared to what story B2 originally
proposed. B2's scope will need to be revised in light of Approach 3.

**Purpose:** Prove the full adapter works end-to-end. Calls `adapter.on_message()`
and `adapter.send()`. `demo_webhook_server.py` must be written as part of US-13.

**Startup sequence (3 terminals):**

```
Terminal 1                              Terminal 2                Meta/Twilio Console
─────────────────────────────           ──────────────            ─────────────────────
uv run python glc/main.py               ngrok http 8765           Webhook URL:
  → GLC gateway on :8111                                          https://abc.ngrok.app/
                                        → prints public URL
Terminal 3
─────────────────────────────
uv run python
  .../US13_demo/scripts/
  demo_webhook_server.py
  → Listens on :8765
```

**Flow — Inbound (receiving a message):**

```
Your Phone
    │ sends WhatsApp message
    ▼
Meta / Twilio
    │ POST https://abc.ngrok.app/
    │ Headers: X-Hub-Signature-256 (Meta) or X-Twilio-Signature (Twilio)
    │ Body: raw wire-format payload
    ▼
ngrok tunnel → localhost:8765
    ▼
demo_webhook_server.py                 ← help_docs/US13_demo/scripts/demo_webhook_server.py
    │ reads raw_body (bytes) + headers (dict)
    │
    ▼
adapter.on_message({                   ← glc/channels/catalogue/whatsapp/adapter.py
    "raw_body": raw_body,
    "headers": headers
})
    │
    ├── _headers()                     normalise header keys to lowercase
    │
    ├── verify_meta_signature()        US-3: HMAC-SHA256 check
    │   or verify_twilio_signature()   US-6: HMAC-SHA1 check
    │   → None if invalid (drop)
    │
    ├── parse_meta_payload()           US-4: extract from_id, text, message_id, timestamp
    │   or parse_twilio_payload()      US-7: extract WaId, Body, MessageSid
    │
    ├── classify("whatsapp", from_id)  glc/security/trust_level.py
    │
    ├── get_pairing_store().owners()   glc/security/pairing.py
    │
    ├── allowed(…)                     glc/security/allowlists.py
    │   → None if stranger in public channel
    │
    └── returns ChannelMessage(
            channel="whatsapp",
            channel_user_id=from_id,
            text=text,
            trust_level="owner_paired"|"user_paired"|"untrusted",
            metadata={"provider":"meta"|"twilio", "message_id":…}
        )
    ▼
demo_webhook_server.py
    │ logs ChannelMessage to console
    │ constructs ChannelReply
    ▼
adapter.send(ChannelReply)             ← glc/channels/catalogue/whatsapp/adapter.py
    │
    ├── build_meta_send_payload()      US-5: {"messaging_product":"whatsapp","to":…}
    │   POST https://graph.facebook.com/…/messages
    │
    └── build_twilio_send_payload()    US-8: {"To":"whatsapp:+…","From":…,"Body":…}
        POST https://api.twilio.com/…/Messages.json
    ▼
Your Phone receives reply
```

**Note:** GLC gateway (Terminal 1 / `glc/main.py`) is running but NOT in this path.
`demo_webhook_server.py` calls the adapter directly. The gateway's allowlist, rate-limit,
and audit pipeline are bypassed. Sufficient for the US-13 demo.

**Script location:**
```
glc/channels/catalogue/whatsapp/help_docs/
└── US13_demo/
    └── scripts/
        └── demo_webhook_server.py     ← TO BE WRITTEN for US-13
```

---

### Approach 3 — Standardized (requires separate PR to shared code)

**Purpose:** The correct long-term solution. The GLC gateway itself receives the
webhook for ALL channels via a generic HTTP route in `channels.py`. No per-channel
server, no manual startup.

**What needs to be added to `glc/routes/channels.py`** (outside our owned path):

```python
@router.get("/v1/channels/{name}/webhook")   # hub.challenge verification (Meta)
@router.post("/v1/channels/{name}/webhook")  # inbound webhook from Meta / Twilio
```

**Flow:**

```
Your Phone
    │ sends WhatsApp message
    ▼
Meta / Twilio
    │ POST https://glc.yourdomain.com/v1/channels/whatsapp/webhook
    ▼
glc/routes/channels.py                 ← POST /v1/channels/{name}/webhook (new route)
    │
    ├── registry.instantiate("whatsapp")   glc/channels/registry.py
    │       scans catalogue/ → finds our Adapter class
    │
    ├── adapter.on_message({           glc/channels/catalogue/whatsapp/adapter.py
    │       "raw_body": await request.body(),
    │       "headers": dict(request.headers)
    │   })
    │   → ChannelMessage
    │
    ├── allowed(…)                     glc/security/allowlists.py
    ├── rate_limiter.check_message()   glc/security/rate_limits.py
    ├── audit_append(…)                glc/audit.py
    │
    ├── agent (stub echo / real runtime)
    │   → ChannelReply
    │
    └── adapter.send(reply)            glc/channels/catalogue/whatsapp/adapter.py
    ▼
Your Phone receives reply
```

**Startup — single command:**

```bash
uv run python glc/main.py              # that's it — all channels, one process
```

No ngrok port split. No separate webhook server process. Configure
`https://glc.yourdomain.com/v1/channels/whatsapp/webhook` in Meta/Twilio console.

**Exact code changes required in `glc/routes/channels.py`:**

```python
# --- New imports needed ---
import os
from fastapi import Request
from fastapi.responses import PlainTextResponse
from glc.channels import registry                  # already exists in the repo

# --- New GET route: Meta hub.challenge verification ---
@router.get("/v1/channels/{name}/webhook")
async def channel_webhook_verify(name: str, request: Request):
    params     = dict(request.query_params)
    mode       = params.get("hub.mode", "")
    token      = params.get("hub.verify_token", "")
    challenge  = params.get("hub.challenge", "")
    # Convention: {CHANNEL_NAME}_VERIFY_TOKEN env var (e.g. WHATSAPP_VERIFY_TOKEN)
    expected   = os.environ.get(f"{name.upper()}_VERIFY_TOKEN", "")
    if mode == "subscribe" and token == expected:
        return PlainTextResponse(challenge)
    from fastapi import HTTPException
    raise HTTPException(status_code=403)

# --- New POST route: inbound webhook from Meta / Twilio ---
@router.post("/v1/channels/{name}/webhook")
async def channel_webhook(name: str, request: Request):
    try:
        adapter = registry.instantiate(name)
    except KeyError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"unknown channel: {name}")

    raw = {
        "raw_body": await request.body(),
        "headers": dict(request.headers),
    }
    msg = await adapter.on_message(raw)
    if msg is None:
        return {"status": "ok"}          # dropped: bad signature / untrusted in public

    limiter  = get_rate_limiter()
    pairings = get_pairing_store()
    owners   = [p.channel_user_id for p in pairings.owners(channel=name)]

    ok, why = allowed(
        msg.channel, msg.channel_user_id,
        owner_ids=owners,
        is_public_channel=bool(msg.metadata.get("is_public_channel", False)),
        was_mentioned=bool(msg.metadata.get("was_mentioned", False)),
    )
    if not ok:
        audit_append(channel=msg.channel, channel_user_id=msg.channel_user_id,
                     trust_level=msg.trust_level, event_type="allowlist_drop",
                     result={"reason": why})
        return {"status": "ok"}

    ok, why = limiter.check_message(msg.channel, msg.channel_user_id)
    if not ok:
        audit_append(channel=msg.channel, channel_user_id=msg.channel_user_id,
                     trust_level=msg.trust_level, event_type="rate_limit",
                     result={"reason": why})
        return {"status": 429, "error": why}

    audit_append(channel=msg.channel, channel_user_id=msg.channel_user_id,
                 trust_level=msg.trust_level, event_type="inbound_message",
                 params={"text": msg.text, "thread_id": msg.thread_id})

    reply = ChannelReply(
        channel=msg.channel,
        channel_user_id=msg.channel_user_id,
        text=f"[glc echo] {msg.text or ''}",
        thread_id=msg.thread_id,
    )
    await adapter.send(reply)
    return {"status": "ok"}
```

**Why this isn't done yet:**
`glc/routes/channels.py` is shared code outside every group's owned path.
Adding these routes requires a **separate PR scoped only to `channels.py`**
under `@theschoolofai` review — same process as the `pyproject.toml` dependency PR
described in HANDOFF §0.2. This is the correct solution for all 15 channels but is
not part of our US-1 through US-15 submission.

---

## Comparison table

| | Approach 1 — Dev/POC | Approach 2 — Our Demo | Approach 3 — Standardized |
|---|---|---|---|
| **Script** | `meta_webhook_test_server.py` | `demo_webhook_server.py` | None (gateway handles it) |
| **Calls adapter.on_message()** | No | Yes | Yes |
| **Calls adapter.send()** | No | Yes | Yes |
| **GLC gateway pipeline used** | No | No | Yes (allowlist, rate-limit, audit) |
| **Processes to start** | 2 (server + ngrok) | 3 (gateway + server + ngrok) | 1 (gateway only) + tunnel |
| **Works for all 15 channels** | No | No (whatsapp only) | Yes (registry-driven) |
| **Requires shared code PR** | No | No | Yes |
| **Status** | Done (US-1) | To be written (US-13) | Not in scope (post US-15) |

---

## Quick reference: env vars required for inbound

| Variable | Provider | Used in |
|---|---|---|
| `WHATSAPP_APP_SECRET` | Meta | `verify_meta_signature()` — HMAC-SHA256 check |
| `WHATSAPP_VERIFY_TOKEN` | Meta | `hub.challenge` GET verification |
| `TWILIO_AUTH_TOKEN` | Twilio | `verify_twilio_signature()` — HMAC-SHA1 check |
| `TWILIO_WEBHOOK_URL` | Twilio | Must exactly match URL registered in Twilio console |

---

## Key files referenced

| File | Role |
|---|---|
| `glc/channels/catalogue/whatsapp/adapter.py` | `on_message()` and `send()` — all adapter logic |
| `glc/channels/registry.py` | Auto-discovers adapter classes from `catalogue/` |
| `glc/routes/channels.py` | WebSocket `/v1/channels/{name}` — and where the HTTP route should be added |
| `glc/main.py` | FastAPI app — mounts all routes, starts gateway |
| `glc/security/trust_level.py` | `classify()` — called inside `on_message()` |
| `glc/security/allowlists.py` | `allowed()` — called inside `on_message()` |
| `glc/security/pairing.py` | `get_pairing_store()` — owner lookup |
| `help_docs/US1_meta_wiring/scripts/meta_webhook_test_server.py` | Approach 1 server |
| `help_docs/US13_demo/scripts/demo_webhook_server.py` | Approach 2 server (to be written) |
