# IMAP/SMTP Channel Adapter

Production-quality IMAP/SMTP adapter for GLC v1. Translates raw RFC 822
email wire format into typed `ChannelMessage` / `ChannelReply` envelopes
that GLC's agent runtime understands.

Live demo server targets **Zoho Mail** (free tier, full IMAP/SMTP, IDLE support).
Works with any standard IMAP/SMTP provider.

---

## File Structure

```
glc/channels/catalogue/imap/
├── adapter.py          # Thin orchestrator — on_message() and send()
├── artifacts.py        # Ephemeral attachment store (all MIME types)
├── connection.py       # IMAP session: LOGIN, SELECT, IDLE, reconnect
├── mime_parser.py      # Pure MIME walker: text/plain + attachments
├── smtp_sender.py      # SMTP STARTTLS sender — stateless per-send
├── uid_tracker.py      # Persistent UID deduplication (SQLite)
├── server.py           # Live demo — Zoho Mail IDLE poll loop
├── schemas.py          # Pydantic types (ImapConfig, ParsedEmail, …)
├── __init__.py
├── .env.example        # Environment variable template
└── .gitignore          # Blocks credentials/tokens from git
```

---

## Architecture

### Design principle: thin adapter, rich modules

`adapter.py` is a pure orchestrator. All protocol logic lives in focused
single-responsibility modules that are independently testable.

```
                    IMAP IDLE / poll (TCP port 993)
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  adapter.on_message(raw)                                     │
│                                                              │
│  1. mime_parser.parse()   → ParsedEmail                      │
│     ├─ strip display name   ("Alice <a@b.com>" → "a@b.com") │
│     ├─ extract text/plain   (prefer over text/html)          │
│     ├─ html fallback        (strip tags — no JS to agent)    │
│     └─ extract attachments  (all MIME types → bytes)         │
│                                                              │
│  2. classify()            → owner_paired | user_paired       │
│     └─ DROP if untrusted + public-channel mode               │
│                                                              │
│  3. _store_attachment()   → art:<sha256[:16]> refs           │
│     └─ ArtifactStore (disk) or mock.store_artifact (tests)   │
│                                                              │
│  4. uid_tracker.mark_seen() → dedup on reconnect             │
│                                                              │
│  Output: ChannelMessage(trust, text, attachments, thread_id) │
└──────────────────────────────────────────────────────────────┘
                               │
                               ▼
                     GLC Gateway / Agent
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  adapter.send(ChannelReply)                                  │
│                                                              │
│  1. _format_reply()       → RFC 5322 EmailMessage            │
│     ├─ From / To / Date                                      │
│     ├─ Subject            "Re: <original subject>"           │
│     ├─ Message-ID         <uuid4@glc>  (fresh per reply)     │
│     ├─ In-Reply-To        <original Message-ID>              │
│     └─ References         <thread chain> <original-id>       │
│                                                              │
│  2. mock.send() / SmtpSender.send()                          │
│     └─ SMTP 421 normalised → {"status": 429}                 │
└──────────────────────────────────────────────────────────────┘
                               │
                        SMTP STARTTLS (port 587)
```

### Module responsibilities

| Module | Single responsibility |
|---|---|
| `mime_parser.py` | Pure MIME → `ParsedEmail`. Zero I/O. |
| `artifacts.py` | Blob store: SHA256 key, TTL, path-traversal guard |
| `uid_tracker.py` | SQLite seen-UID set — dedup after crash/reconnect |
| `smtp_sender.py` | EHLO → STARTTLS → AUTH → DATA. Stateless per-send. |
| `connection.py` | IMAP SSL session, IDLE, exponential reconnect backoff |
| `adapter.py` | Wires modules together. No protocol logic. |
| `server.py` | Poll loop + step-by-step pipeline logging |

---

## Why IMAP/SMTP needs its own architecture

| Concern | How this adapter handles it |
|---|---|
| Long-lived TCP connection | `connection.py` — IDLE + exponential reconnect |
| Silent connection drops | `ConnectionResetError` caught → `reconnect()` |
| Duplicate messages on reconnect | `uid_tracker.py` — SQLite persists seen UIDs |
| Native RFC 822 bytes | `mime_parser.py` — no extra encode/decode layer |
| Stale SMTP connections | `smtp_sender.py` — fresh session per send |
| All MIME attachment types | `artifacts.py` — image, audio, video, file |
| Thread continuity | `In-Reply-To` + `References` headers on every reply |
| HTML injection to agent | `mime_parser` strips HTML tags before text reaches agent |
| Display names in From header | `_strip_display_name()` → bare email for trust lookup |
| SMTP back-pressure | SMTP 421 → normalised to `{"status": 429}` |

---

## How to Replicate

### Prerequisites

- Python 3.11+
- A Zoho Mail account (free tier at [zoho.com/mail](https://www.zoho.com/mail/))
- `uv` installed (`pip install uv`)

### Step 1 — Clone and install

```bash
git clone https://github.com/pushpendra-aibot/glc_v1_imap.git
cd glc_v1_imap
uv sync
```

### Step 2 — Zoho Mail setup (one-time)

1. **Create account**: [zoho.com/mail](https://www.zoho.com/mail/) — free tier is sufficient
2. **Enable IMAP**:
   - Settings → Mail Accounts → IMAP/SMTP Access → **Enable IMAP**
   - Note: use `imap.zoho.in` (India) or `imap.zoho.com` (global)
3. **Generate App Password**:
   - [accounts.zoho.in](https://accounts.zoho.in/home) → Security → App Passwords → Add
   - Name it "GLC Bot" — copy the generated password
   - ⚠️ Use this App Password, **not** your Zoho login password

### Step 3 — Configure environment

```bash
cp glc/channels/catalogue/imap/.env.example .env
```

Edit `.env` with your credentials:

```bash
IMAP_HOST=imap.zoho.in
IMAP_PORT=993
IMAP_USER=bot@<your-domain>.com
IMAP_PASSWORD=your-zoho-app-password

SMTP_HOST=smtp.zoho.in
SMTP_PORT=587
SMTP_USER=bot@<your-domain>.com
SMTP_PASSWORD=your-zoho-app-password

BOT_FROM=bot@<your-domain>.com
GLC_IMAP_OWNER=owner@example.com
```

### Step 4 — Run the live demo server

```bash
cd glc_v1_imap
uv sync
uv run python -m glc.channels.catalogue.imap.server
```

### Step 5 — Run tests

```bash
# 7 CI-required tests
uv run pytest tests/channels/test_imap.py -v

# 15 extended tests
uv run pytest tests/test_imap_extended.py -v
```

On success, the 7 CI-required tests should report:


Detailed CI test case expectations:

- `test_on_message_owner_returns_valid_envelope`
  - the owner message is converted to `ChannelMessage`
  - `channel == imap`, `channel_user_id == OWNER_ID`, `trust_level == owner_paired`
  - message text contains the inbound body

- `test_on_message_stranger_is_untrusted`
  - a stranger message is accepted but marked `untrusted`
  - `channel_user_id == STRANGER_ID`

- `test_send_emits_valid_wire_payload`
  - outbound `ChannelReply` produces SMTP wire payload
  - `to` matches the owner, and raw bytes contain `From:`, `To:`, `Subject:`, and reply text

- `test_disconnect_is_handled`
  - the adapter survives an IMAP disconnect event cleanly
  - no exception should be raised while processing a new owner message after disconnect

- `test_rate_limit_propagates_429`
  - SMTP 421 back-pressure is surfaced as a structured result
  - the adapter may return `status` 421 or normalise to 429

- `test_allowlist_silently_drops_stranger_in_public`
  - public-channel mode should not deliver stranger messages
  - result is `None` or `trust_level == untrusted`

- `test_channel_specific_behaviour_pdf_attachment_to_artifact`
  - a multipart PDF email produces a text body and one `application/pdf` attachment
  - attachment ref must start with `art:` and the PDF bytes must be stored in the mock artifact store

---

## Live Demo

The server polls the Zoho INBOX every 5 seconds. Send an email from your
personal account (`GLC_IMAP_OWNER`) to the bot account to observe the
full pipeline.

### Pipeline log output

```
[BOOT ] Owner paired: you@personal.com → owner_paired
[BOOT ] IMAP/SMTP server started — polling every 5s
[BOOT ] Send an email to bot@<your-domain>.com to test the pipeline
[IMAP ] Connected to imap.zoho.in:993
[IMAP ] Watching INBOX

# → Send an email from your personal address to the bot ←

[FETCH] UID 1042 — From: you@personal.com — Subject: Hey GLC
[MSG  ] From=you@personal.com | trust=owner_paired | text='Hello bot!' | attachments=0
[REPLY] {'status': 250, 'message_id': '<3f2a...@glc>'}
```

## Proof of live delivery

The screenshots below show the real Zoho bot reply delivered from the IMAP adapter and received in the personal inbox.

![Zoho inbox showing the sent message](Zohomail.png)

*Zoho Mail inbox with the adapter reply message visible.*

![Gmail inbox showing the reply classified as Spam](PersonalEmail.png)

*Gmail view showing the reply from `EAGV3S11IMAP@zohomail.in` delivered to the personal account.*

### What each log prefix means

| Prefix | Step |
|---|---|
| `[BOOT ]` | Startup — owner paired, connection opened |
| `[IMAP ]` | IMAP connection events (connect, IDLE, reconnect) |
| `[FETCH]` | Inbound email detected — UID + From + Subject |
| `[MSG  ]` | `ChannelMessage` produced — trust level + text snippet |
| `[DROP ]` | Message silently dropped (untrusted in public-channel mode) |
| `[REPLY]` | SMTP send result |

### Reconnection demo

Kill the server and restart — the `UidTracker` ensures no email is
re-delivered. Drop the network briefly — `connection.py` reconnects
with exponential backoff (1 → 2 → 4 → 8 → … → 60 seconds).

---

## Pipeline Details

### Inbound: Email → ChannelMessage

| Step | Method | What it does |
|---|---|---|
| 1 | `mime_parser.parse()` | Decode RFC 822 bytes → `ParsedEmail` |
| 2 | `_strip_display_name()` | `"Alice <a@b.com>"` → `"a@b.com"` |
| 3 | `classify()` | Lookup `(channel, sender)` in pairing store |
| 4 | Public-channel gate | Drop untrusted if `is_public_channel=True` |
| 5 | `_store_attachment()` | Hash blob → `art:<sha>` ref in ArtifactStore |
| 6 | `uid_tracker.mark_seen()` | Record UID so reconnect skips it |
| 7 | Return | `ChannelMessage(trust, text, attachments, thread_id)` |

### Outbound: ChannelReply → Email

| Step | Method | What it does |
|---|---|---|
| 1 | `_format_reply()` | Build RFC 5322 `EmailMessage` with thread headers |
| 2 | `SmtpSender.send()` | EHLO → STARTTLS → AUTH → DATA |
| 3 | Error mapping | SMTP 421 → `{"status": 429, "error": "..."}` |

---

## Trust Levels

| Level | Who | Policy |
|---|---|---|
| `owner_paired` | `GLC_IMAP_OWNER` email (set at startup) | All tools |
| `user_paired` | Explicitly paired contacts | Read-only tools |
| `untrusted` | Everyone else | Policy-restricted (dropped in public-channel mode) |

Trust is resolved from `~/.glc/pairings.sqlite`. The owner is registered
at server startup:

```python
store.force_pair_owner("imap", owner_email, user_handle="owner")
```

Or set via environment variable:

```bash
export GLC_IMAP_OWNER="your-personal@email.com"
```

---

## Artifact Store

Attachments (all MIME types) are stored ephemerally under `~/.glc/artifacts/<sha256[:16]>`:

- Written when a MIME attachment is extracted from an inbound email
- Ref format: `art:<16-hex>` — returned in `Attachment.ref`
- Auto-expires after **5 minutes** (`cleanup_expired()`)
- **Path-traversal protected**: ref validated as exactly 16 lowercase hex chars
  before any file I/O — `art:../etc/passwd` → `ValueError`

```python
store = ArtifactStore()
ref = store.store(pdf_bytes, mime="application/pdf", filename="doc.pdf")
# ref = "art:a3f8b2c1d4e5f6a7"
data = store.get(ref)    # → bytes
store.remove(ref)        # explicit cleanup
store.cleanup_expired()  # TTL-based cleanup (call periodically)
```

---

## Wire Format Quirks

**IMAP FETCH returns raw RFC 822 bytes** — no base64 encoding layer, no JSON wrapper.
The adapter passes them directly to `email.message_from_bytes()`.

**Multipart MIME**: Most emails carry both `text/plain` and `text/html`.
The adapter always picks `text/plain` to avoid injecting HTML/JS into the
agent context. If only `text/html` exists, tags are stripped before the
text reaches the agent.

**Display names in From**: Zoho (and most providers) format the From header
as `"Display Name <address@domain.com>"`. The adapter strips to the bare
address before trust lookup — otherwise `classify()` sees the display-name
string and returns `untrusted` for even the owner.

**Thread continuity**: Replies include:
- `In-Reply-To: <original-message-id>` — threads reply in the MUA
- `References: <chain> <original-id>` — full thread chain for MUAs
- `Message-ID: <uuid4@glc>` — fresh unique ID per reply

**SMTP 421 back-pressure**: Zoho (and most SMTP servers) emit `421 Service
not available, try later` under load. The adapter normalises this to
`{"status": 429}` so callers can apply standard rate-limit handling.

**UID deduplication**: IMAP UIDs are integers unique per mailbox (not globally).
After a reconnect, `SEARCH UNSEEN` returns all unread UIDs — the `UidTracker`
SQLite set prevents reprocessing messages that were already handled.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `IMAP_HOST` | `imap.zoho.in` | IMAP server hostname |
| `IMAP_PORT` | `993` | IMAP port (993 = SSL/TLS) |
| `IMAP_USER` | *(required)* | IMAP login address |
| `IMAP_PASSWORD` | *(required)* | Zoho App Password — never your login password |
| `SMTP_HOST` | `smtp.zoho.in` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port (587 = STARTTLS) |
| `SMTP_USER` | *(required)* | SMTP login address |
| `SMTP_PASSWORD` | *(required)* | Zoho App Password |
| `BOT_FROM` | `IMAP_USER` | From address in outbound emails |
| `GLC_IMAP_OWNER` | *(required)* | Owner email — gets `owner_paired` trust at startup |
| `GLC_ARTIFACTS_DIR` | `~/.glc/artifacts` | Attachment storage directory |
| `GLC_IMAP_UID_DB` | `~/.glc/imap_uids.sqlite` | UID deduplication database |
| `GLC_PAIRING_DB` | `~/.glc/pairings.sqlite` | Trust pairing database |

See [`.env.example`](.env.example) for a copy-paste template.
`.env` is gitignored — never commit real credentials.

---

## Zoho Mail Server Reference

| Setting | Value |
|---|---|
| IMAP hostname | `imap.zoho.in` (India) / `imap.zoho.com` (global) |
| IMAP port | `993` — SSL/TLS |
| SMTP hostname | `smtp.zoho.in` (India) / `smtp.zoho.com` (global) |
| SMTP port | `587` — STARTTLS |
| Auth method | Email address + App Password |
| IMAP IDLE | ✅ Supported |
| Free tier limits | 5 GB storage, 1 domain |

---

## Tests

### CI-required (7 tests) — `tests/channels/test_imap.py`

| Test | What it checks |
|---|---|
| `test_on_message_owner_returns_valid_envelope` | Owner trust, valid ChannelMessage shape |
| `test_on_message_stranger_is_untrusted` | Unknown sender → `untrusted` |
| `test_send_emits_valid_wire_payload` | Outbound `{from, to, raw}` with RFC 5322 headers |
| `test_disconnect_is_handled` | IDLE disconnect → no crash, message still processed |
| `test_rate_limit_propagates_429` | SMTP 421 → status 421 or 429 to caller |
| `test_allowlist_silently_drops_stranger_in_public` | Public-channel gate |
| `test_channel_specific_behaviour_pdf_attachment_to_artifact` | PDF → `art:` ref in artifact store |

### Extended (15 tests) — `tests/test_imap_extended.py`

| Group | Tests | Covers |
|---|---|---|
| A — Robustness | 1–3 | Empty raw, missing key, corrupt bytes |
| B — MIME | 4–6 | HTML-only stripping, unicode (emoji/CJK/Devanagari), empty body |
| C — Trust | 7 | Display-name stripping for trust lookup |
| D — Attachments | 8–9 | Single PDF, PDF + PNG multiple types |
| E — Thread headers | 10–11 | `In-Reply-To`, `References` in outbound reply |
| F — ArtifactStore | 12–13 | store/get/remove lifecycle, path-traversal guard |
| G — UidTracker | 14 | Deduplication, idempotent `mark_seen` |
| H — Subject cache | 15 | Two threads → each gets correct `Re: <subject>` |

```bash
# Run all IMAP tests
uv run pytest tests/channels/test_imap.py tests/test_imap_extended.py -v
```

---

## Submission

Open a PR that:

- Passes `pytest tests/channels/test_imap.py` (7 CI tests)
- Passes `pytest tests/test_imap_extended.py` (15 extended tests)
- Updates `CLAIMS.md` with your team name for the `imap` channel

CI gates merge through branch protection.
