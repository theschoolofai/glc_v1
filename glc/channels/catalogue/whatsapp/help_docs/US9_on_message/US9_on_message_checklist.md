# US-9: on_message orchestrator — Strategy & Checklist

**Branch:** `feature/us9-on-message` (or `US-9-on_message_ochestration`)
**File to change:** `glc/channels/catalogue/whatsapp/adapter.py`
**Depends on:** US-3, US-4, US-6, US-7 (all merged to `integration` before starting)
**Feeds into:** US-10 (`send` orchestrator), US-11 Phase 2 (Twilio orchestrator tests), US-12 (QA gate)

---

## Strategy

### What US-9 delivers

The `Adapter.on_message()` method — the dual-provider inbound orchestrator that wires
together every Wave 1 helper into a single `ChannelMessage | None` envelope:

```python
async def on_message(self, raw: Any) -> ChannelMessage | None:
```

It is the **first story that makes the fixed Meta test suite pass** (tests 1, 2, 4, 6, 7).
Tests 3 and 5 exercise `send()` and were already green after US-5.

### End-to-end flow

```
raw input
    │
    ├─ mock present? → mock.pop_disconnect()   (Test 4 — no-op disconnect flag)
    │
    ├─ detect provider + input shape
    │     Shape B: {"raw_body": bytes, "headers": dict}  → verify signature first
    │     Shape A: bare dict                             → skip verification (tests only)
    │
    ├─ verify (Shape B only) → parse → None on failure
    │
    ├─ classify("whatsapp", from_id)
    ├─ allowed(..., owner_ids, is_public_channel, was_mentioned=False)
    ├─ drop if: not ok AND is_public AND trust == "untrusted"   (Test 6)
    │
    └─ build ChannelMessage(metadata={"provider": "meta"|"twilio", "message_id": ...})
```

### Two input shapes (Meta and Twilio)

From HANDOFF §4.2 — `on_message(raw)` accepts **two shapes**:

| Shape | Looks like | Used by | Meaning |
|---|---|---|---|
| **A** | Bare dict — already-decoded body | Tests 1, 2, 4, 6; Twilio manual checks | Signature verified upstream (or test isolation) |
| **B** | `{"raw_body": bytes, "headers": dict}` | Test 7; real production webhooks | Verify signature first, then decode |

**Provider detection:**

| Signal | Provider | Verify helper | Parse helper |
|---|---|---|---|
| Header `X-Hub-Signature-256` | Meta | `verify_meta_signature()` (US-3) | `parse_meta_payload()` (US-4) |
| Header `X-Twilio-Signature` | Twilio | `verify_twilio_signature()` (US-6) | `parse_twilio_payload()` (US-7) |
| Dict has `"entry"` key | Meta | none (Shape A) | `parse_meta_payload()` |
| Dict has `"From"` + `"Body"` | Twilio | none (Shape A) | `parse_twilio_payload()` — **requires `WaId`** (US-7) |

In production, every real webhook is Shape B. Shape A exists so the fixed suite can test
trust classification without standing up a signing layer.

### Private helpers added in US-9

Three module-level helpers keep `on_message` readable:

```python
def _parse_form_body(raw_body: bytes) -> dict[str, str]:
    """Twilio Shape B: form-urlencoded bytes → flat str dict."""

def _headers(raw: Any) -> dict[str, str]:
    """Extract headers dict from Shape B input."""

def _to_channel_message(parsed: dict, *, provider: str) -> ChannelMessage:
    """Map parsed dict → ChannelMessage with trust + timestamps."""
```

### Full `on_message` implementation (reference)

```python
async def on_message(self, raw: Any) -> ChannelMessage | None:
    mock = self.config.get("mock")
    if mock is not None:
        mock.pop_disconnect()

    headers = _headers(raw)
    is_public = bool(self.config.get("is_public_channel", False))
    owner_ids = [r.channel_user_id for r in get_pairing_store().owners("whatsapp")]
    parsed: dict[str, Any] | None = None
    provider = "meta"

    if isinstance(raw, dict) and "raw_body" in raw:
        raw_body = raw["raw_body"]
        if not isinstance(raw_body, bytes):
            return None

        if headers.get("X-Twilio-Signature"):
            params = _parse_form_body(raw_body)
            url = os.environ.get("TWILIO_WEBHOOK_URL", "")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
            if not verify_twilio_signature(
                url, params, headers.get("X-Twilio-Signature", ""), auth_token
            ):
                return None
            parsed = parse_twilio_payload(params, datetime.now(UTC))
            provider = "twilio"
        elif headers.get("X-Hub-Signature-256"):
            if not verify_meta_signature(raw_body, headers):
                return None
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                return None
            parsed = parse_meta_payload(body)
            provider = "meta"
        else:
            return None
    elif isinstance(raw, dict) and raw.get("entry"):
        parsed = parse_meta_payload(raw)
        provider = "meta"
    elif isinstance(raw, dict) and "From" in raw and "Body" in raw:
        parsed = parse_twilio_payload(raw, datetime.now(UTC))
        provider = "twilio"
    else:
        return None

    if parsed is None:
        return None

    trust = classify("whatsapp", parsed["from_id"])
    ok, _ = allowed(
        "whatsapp",
        parsed["from_id"],
        owner_ids=owner_ids,
        is_public_channel=is_public,
        was_mentioned=False,
    )
    if not ok and is_public and trust == "untrusted":
        return None

    return _to_channel_message(parsed, provider=provider)
```

### Design decisions — each one is deliberate

**Shape B checks Twilio header before Meta:**
If both headers were present (impossible in production), Twilio wins because
`X-Twilio-Signature` is checked first. Real deployments never send both.

**Allowlist drop is narrower than HANDOFF §7.9 step 6:**
HANDOFF says "if not allowed, return None." Strict application would break tests 1 and 2
because `whatsapp` is `enabled: false` in `channels.yaml` — `allowed()` returns `False`
for everyone, including owners. The implementation only drops when:

```python
not ok and is_public and trust == "untrusted"
```

This matches test expectations:
- Owner in DM (disabled channel) → deliver as `owner_paired` (Test 1)
- Stranger in DM → deliver as `untrusted` (Test 2)
- Stranger in public → silently drop (Test 6)

**`was_mentioned=False` always:**
Neither Meta Cloud API nor Twilio WhatsApp sandbox has a group-chat @mention concept.

**Meta timestamp → UTC datetime; Twilio uses receive time:**
Meta: `datetime.fromtimestamp(int(parsed["timestamp"]), tz=UTC)` from webhook epoch string.
Twilio: `parse_twilio_payload(..., datetime.now(UTC))` stores `received_at` as the timestamp
(US-7 design — Twilio form posts don't carry a reliable message epoch in all variants).

**Twilio Shape A requires `WaId`:**
HANDOFF fallback mentions `"From"`/`"Body"`, but US-7's `parse_twilio_payload` requires
`WaId` for `from_id`. Real Twilio WhatsApp webhooks always include `WaId`. A bare
`{From, Body}` dict without `WaId` correctly returns `None`.

**`send()` unchanged:**
US-9 only implements inbound orchestration. Outbound dual-provider dispatch is US-10.

### What US-9 does NOT do

- Does NOT modify US-3/US-4/US-6/US-7 helpers — only calls them
- Does NOT implement Twilio outbound (`build_twilio_send_payload` dispatch) — US-10
- Does NOT add outbound pairing guard on `send()` — US-10
- Does NOT add US-11 Phase 2 orchestrator tests — separate story (recommended before US-12)
- Does NOT handle disconnect detection logic — Test 4 only requires `pop_disconnect()` not to crash

### How helpers interlock

```
US-3  verify_meta_signature()  ──┐
US-4  parse_meta_payload()     ──┼── on_message() ──→ ChannelMessage | None
US-6  verify_twilio_signature()──┤
US-7  parse_twilio_payload()   ──┘
         │
         ├── classify()           (glc/security/trust_level.py)
         ├── get_pairing_store()  (glc/security/pairing.py)
         └── allowed()            (glc/security/allowlists.py)
```

### ChannelMessage output shape

```python
ChannelMessage(
    channel="whatsapp",
    channel_user_id=parsed["from_id"],           # bare E.164
    user_handle=parsed["profile_name"] or parsed["from_id"],
    text=parsed["text"],                         # None for media / non-text
    trust_level=classify(...),                   # owner_paired | user_paired | untrusted
    arrived_at=<datetime>,
    metadata={
        "provider": "meta" | "twilio",
        "message_id": parsed["message_id"],
    },
)
```

---

## Checklist

### Pre-flight

- [x] Confirm active branch is `feature/us9-on-message` (based on latest `integration`)
- [x] Confirm US-3, US-4, US-6, US-7 are merged to `integration`
- [x] Re-read HANDOFF §4.2 (two input shapes) and §7.9
- [x] Re-read fixed tests in
      [test_whatsapp.py](../../../../../../../tests/channels/test_whatsapp.py)
- [x] Re-read mock helpers in
      [whatsapp_mock.py](../../../../../../../tests/channels/mocks/whatsapp_mock.py)

### Implementation

- [x] Open [adapter.py](../../../adapter.py)
- [x] Add imports: `json`, `UTC`/`datetime`, `parse_qs`, `allowed`, `get_pairing_store`, `classify`
- [x] Add private helpers: `_parse_form_body`, `_headers`, `_to_channel_message`
- [x] Replace `on_message` `NotImplementedError` stub with dual-provider orchestrator
- [x] Leave `send()` unchanged (Meta-only minimal wiring from US-5)

### Automated verification — fixed Meta suite (7 tests)

Run the full suite:

```bash
uv run pytest tests/channels/test_whatsapp.py -v
```

- [x] **Test 1 — `test_on_message_owner_returns_valid_envelope`** **PASS**
      Owner → `trust_level == "owner_paired"`, correct text and `arrived_at`

- [x] **Test 2 — `test_on_message_stranger_is_untrusted`** **PASS**
      Stranger → `trust_level == "untrusted"`, message not dropped

- [x] **Test 3 — `test_send_emits_valid_wire_payload`** **PASS**
      (US-5 — unchanged by US-9)

- [x] **Test 4 — `test_disconnect_is_handled`** **PASS**
      `force_disconnect()` + `on_message()` does not raise

- [x] **Test 5 — `test_rate_limit_propagates_429`** **PASS**
      (US-5 — unchanged by US-9)

- [x] **Test 6 — `test_allowlist_silently_drops_stranger_in_public`** **PASS**
      `is_public_channel=True` + stranger → `None`

- [x] **Test 7 — `test_channel_specific_behaviour_signature_verification`** **PASS**
      Unsigned → `None`; tampered → `None`; valid HMAC → envelope with correct text

### Automated verification — Twilio helper suite (US-6 unit tests)

```bash
uv run pytest glc/channels/catalogue/whatsapp/tests/test_twilio_path.py -v
```

- [x] **4 tests — `verify_twilio_signature` isolation** **PASS**
      (US-6 — unchanged by US-9; confirms helper still works)

### Manual verification — Twilio orchestrator (recommended until US-11 Phase 2)

US-11 Phase 2 will add automated Twilio `on_message` tests. Until then, run:

```bash
uv run python -c "
import asyncio, os
from urllib.parse import urlencode
from twilio.request_validator import RequestValidator
from glc.channels.catalogue.whatsapp.adapter import Adapter
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.whatsapp_mock import OWNER_ID, STRANGER_ID

async def main():
    store = get_pairing_store()
    store.force_pair_owner('whatsapp', OWNER_ID, user_handle='owner')
    try:
        adapter = Adapter(config={})
        url = 'https://example.com/webhook/whatsapp'
        token = 'test_auth_token'
        os.environ['TWILIO_WEBHOOK_URL'] = url
        os.environ['TWILIO_AUTH_TOKEN'] = token

        # Shape A — owner
        msg = await adapter.on_message({
            'WaId': OWNER_ID, 'From': f'whatsapp:+{OWNER_ID}',
            'Body': 'hello twilio', 'NumMedia': '0',
            'MessageSid': 'SM123', 'ProfileName': 'owner',
        })
        assert msg and msg.metadata['provider'] == 'twilio'

        # Shape A — stranger
        msg2 = await adapter.on_message({
            'WaId': STRANGER_ID, 'From': f'whatsapp:+{STRANGER_ID}',
            'Body': 'hi', 'NumMedia': '0', 'MessageSid': 'SM124',
        })
        assert msg2 and msg2.trust_level == 'untrusted'

        # Shape B — signed webhook
        params = {'WaId': OWNER_ID, 'From': f'whatsapp:+{OWNER_ID}',
                  'Body': 'signed', 'NumMedia': '0', 'MessageSid': 'SM456'}
        raw = urlencode(params).encode()
        sig = RequestValidator(token).compute_signature(url, params)
        msg3 = await adapter.on_message({'raw_body': raw, 'headers': {'X-Twilio-Signature': sig}})
        assert msg3 and msg3.text == 'signed'

        print('ALL TWILIO ORCHESTRATOR CHECKS PASSED')
    finally:
        store.revoke('whatsapp', OWNER_ID)

asyncio.run(main())
"
```

- [x] Twilio Shape A owner → `provider == "twilio"` **PASS**
- [x] Twilio Shape A stranger → `trust_level == "untrusted"` **PASS**
- [x] Twilio Shape B valid signature → envelope **PASS**
- [x] Twilio Shape B bad signature → `None` **PASS**
- [x] Missing `WaId` on Shape A → `None` **PASS**

### Quality gates

- [x] `ruff check glc/channels/catalogue/whatsapp/` → **All checks passed**
- [x] `mypy glc/channels/catalogue/whatsapp/adapter.py` → **Success: no issues found**
- [ ] `check_pr_boundaries.py --base integration --head HEAD` → run before opening mini-PR

### Commit

- [ ] Staged: `glc/channels/catalogue/whatsapp/adapter.py` + `help_docs/US9_on_message/`
- [ ] Committed: `US-9: on_message orchestrator — Meta + Twilio dual-provider inbound`
- [ ] Push:
      ```bash
      git push -u origin feature/us9-on-message
      ```

### Mini-PR

- [ ] Open pull request inside the fork:
  - **base:** `integration`
  - **compare:** `feature/us9-on-message`
  - **title:** `US-9: on_message orchestrator (dual-provider inbound)`
  - **body:** all 7 fixed Meta tests green; Twilio manual orchestrator checks documented
- [ ] PR description confirms: `send()` unchanged; no hardcoded secrets
- [ ] Mini-PR approved and merged to `integration`

---

## Edge cases to be aware of

| Scenario | How it's handled |
|---|---|
| `raw_body` present but not `bytes` | Return `None` immediately |
| Shape B with no signature header | Return `None` (neither Meta nor Twilio) |
| Meta delivery/status webhook (no `messages`) | `parse_meta_payload` → `None` → drop |
| Meta non-text message (`type != "text"`) | Envelope with `text=None` |
| Twilio media message (`NumMedia != "0"`) | Envelope with `text=None` |
| Twilio `{From, Body}` without `WaId` | `parse_twilio_payload` → `None` |
| Invalid Meta JSON in Shape B | `json.JSONDecodeError` → `None` |
| `whatsapp` disabled in `channels.yaml` | Owners/strangers in DM still pass; public strangers dropped |
| Both signature headers (theoretical) | Twilio branch wins (checked first) |
| Missing `TWILIO_WEBHOOK_URL` / `TWILIO_AUTH_TOKEN` | Signature verify fails → `None` |
| `TWILIO_WEBHOOK_URL` mismatch vs Twilio console | Signature verify fails → `None` — URL must match exactly |

---

## Dependency map

```
US-3  verify_meta_signature()  ──┐
US-4  parse_meta_payload()     ──┤
US-6  verify_twilio_signature()──┼── US-9  on_message()
US-7  parse_twilio_payload()   ──┘         │
                                             ├── Tests 1, 2, 4, 6, 7 (fixed Meta suite)
                                             └── US-11 Phase 2 (Twilio orchestrator tests)
                                                      │
                                                      └── US-12 QA gate (both suites green)
```

US-10 (`send` orchestrator) can proceed in parallel once US-5 and US-8 are merged — it does
not block on US-9, but US-12 requires both US-9 and US-10 merged.

---

## Quick reference: test constants and env vars

From [whatsapp_mock.py](../../../../../../../tests/channels/mocks/whatsapp_mock.py):

| Constant | Value | Used in |
|---|---|---|
| `OWNER_ID` | `"919999990000"` | Test 1, pairing fixture |
| `STRANGER_ID` | `"917777770000"` | Tests 2, 6 |
| `DEFAULT_APP_SECRET` | `"test-app-secret"` | Test 7 (autouse fixture sets env) |

Environment variables for production / Twilio manual checks:

| Variable | Provider | Purpose |
|---|---|---|
| `WHATSAPP_APP_SECRET` | Meta | HMAC verify (Shape B) |
| `TWILIO_AUTH_TOKEN` | Twilio | Signature verify (Shape B) |
| `TWILIO_WEBHOOK_URL` | Twilio | Must match exact public webhook URL Twilio signed |

Config keys read by `on_message`:

| Key | Default | Purpose |
|---|---|---|
| `config["mock"]` | none | Test mock; triggers `pop_disconnect()` |
| `config["is_public_channel"]` | `False` | Allowlist public-channel drop (Test 6) |

---

## What's next

| Story | What it adds |
|---|---|
| **US-10** | Dual-provider `send()` + outbound pairing guard |
| **US-11 Phase 2** | Automated Twilio `on_message` tests in `test_twilio_path.py` |
| **US-12** | Combined QA gate — both test suites must be green |
| **US-13** | Demo recording — real Meta + Twilio round-trips on phone |
