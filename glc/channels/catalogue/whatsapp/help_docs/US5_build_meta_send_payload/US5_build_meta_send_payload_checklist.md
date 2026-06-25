# US-5: build_meta_send_payload — Strategy & Checklist

**Branch:** `feature/us5-build-meta-send-payload`
**File to change:** `glc/channels/catalogue/whatsapp/adapter.py`
**Depends on:** nothing (Wave 1, fully parallel)
**Feeds into:** US-10 (`send` orchestrator — dual-provider + outbound guard)

---

## Strategy

### What US-5 delivers

A module-level helper function in `adapter.py`:

```python
def build_meta_send_payload(reply: ChannelReply) -> dict[str, Any]:
```

It translates a GLC `ChannelReply` into the JSON body Meta's Graph API expects for a
text message send:

```
POST https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages
Authorization: Bearer {WHATSAPP_TOKEN}
Content-Type: application/json
```

### Outbound wire shape (authoritative)

From `whatsapp_mock.py` docstring and `test_send_emits_valid_wire_payload`:

```python
{
    "messaging_product": "whatsapp",
    "to": "<E164>",           # bare number, no "+" or "whatsapp:" prefix
    "type": "text",
    "text": {"body": "..."},  # NOT a top-level string — nested dict required
}
```

Field mapping from `ChannelReply`:

| Graph API field | Source |
|---|---|
| `messaging_product` | literal `"whatsapp"` |
| `to` | `reply.channel_user_id` |
| `type` | literal `"text"` |
| `text.body` | `reply.text` |

### Full implementation

```python
def build_meta_send_payload(reply: ChannelReply) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": reply.channel_user_id,
        "type": "text",
        "text": {"body": reply.text},
    }
```

### Minimal `send()` wiring (required for tests)

US-5's acceptance criteria reference `test_send_emits_valid_wire_payload`, which calls
`adapter.send()` — not the helper directly. A thin `send()` implementation is included
following `docs/ADAPTER_GUIDE.md` §4:

```python
async def send(self, reply: ChannelReply) -> Any:
    body = build_meta_send_payload(reply)
    mock = self.config.get("mock")
    if mock is not None:
        return await mock.send(body)
    return body
```

When `config["mock"]` is set (test suite), the payload is dispatched to
`WhatsappMock.send()` and recorded in `mock.send_log`. When no mock is present, the
built dict is returned for US-10 to POST to the real Graph API.

### Design decisions — each one is deliberate

**Nested `text.body`, not a flat string:**
Meta's Cloud API requires `{"text": {"body": "..."}}`. Adapters that emit
`{"text": "hi"}` fail `test_send_emits_valid_wire_payload` by design.

**`to` uses `channel_user_id` as-is:**
Meta expects E.164 without `+` (e.g. `919999990000`). The adapter does not strip or
add prefixes — pairing and inbound parsing already store bare IDs.

**Pure helper + thin `send()`:**
`build_meta_send_payload` stays a pure function (testable in isolation). HTTP auth,
rate-limit handling, pairing guard, and Twilio dispatch are deferred to US-10.

**No real HTTP in US-5:**
Production sends need `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and error handling.
US-1's round-trip script proved wiring works; US-10 integrates that into the adapter.

### Placement decision

`build_meta_send_payload` lives as a **module-level function** in `adapter.py`, after
`parse_meta_payload` and before the `Adapter` class. Same rationale as US-3/US-4:
- Pure function — directly unit-testable
- US-10's `send()` calls it internally
- HANDOFF §2.7 confirms helper placement is the team's choice

### What US-5 does NOT do

- Does NOT implement `on_message` — that is US-9
- Does NOT add the outbound pairing guard — US-10 (`get_pairing_store().lookup(...)`)
- Does NOT POST to the real Graph API — US-10 (or manual US-1 script for wiring proof)
- Does NOT handle Twilio sends — US-8 (`build_twilio_send_payload`) + US-10 dispatch
- Does NOT pass all 7 tests — only the two send-related structural tests (3 and 5)

### How the mock and function interlock

```
adapter.py                              whatsapp_mock.py
──────────                              ────────────────
build_meta_send_payload(reply)     →    Adapter.send() calls mock.send(body)
  .to = reply.channel_user_id              send_log.append(payload)
  .text.body = reply.text                  returns messages[].id on success
                                           returns {status: 429, error: {code: 80007}}
                                           when rate_limited=True
```

### Real-world link (US-1 Step 15)

The US-1 round-trip script already used this exact shape:

```python
{
    "messaging_product": "whatsapp",
    "to": recipient,
    "type": "text",
    "text": {"body": "Round-trip confirmed from GLC US-1!"},
}
```

US-5 codifies that one-off script logic as a reusable adapter helper.

### How US-10 will extend `send()` (preview)

```python
async def send(self, reply: ChannelReply) -> Any:
    rec = get_pairing_store().lookup("whatsapp", reply.channel_user_id)
    if rec is None:
        return {"error": "recipient not paired", "code": "outbound_blocked"}

    provider = reply.metadata.get("provider", "meta")
    if provider == "twilio":
        body = build_twilio_send_payload(reply)  # US-8
        ...
    else:
        body = build_meta_send_payload(reply)    # US-5
        ...
```

---

## Checklist

### Pre-flight

- [x] Confirm active branch is `feature/us5-build-meta-send-payload`
- [x] Confirm branch is based on `integration` (not `main`)
- [x] Re-read outbound shape in
      [whatsapp_mock.py](../../../../../../../tests/channels/mocks/whatsapp_mock.py)
      (lines 12–14) and send assertions in
      [test_whatsapp.py](../../../../../../../tests/channels/test_whatsapp.py)
      (`test_send_emits_valid_wire_payload`, lines 72–85)
- [x] Re-read HANDOFF §7.5

### Implementation

- [x] Open [adapter.py](../../../adapter.py)
- [x] Added `build_meta_send_payload` as a **module-level function** after
      `parse_meta_payload` (before the `Adapter` class):
      ```python
      def build_meta_send_payload(reply: ChannelReply) -> dict[str, Any]:
          return {
              "messaging_product": "whatsapp",
              "to": reply.channel_user_id,
              "type": "text",
              "text": {"body": reply.text},
          }
      ```
- [x] Wired minimal `Adapter.send()` to call `build_meta_send_payload` and dispatch
      via `config["mock"]` when present (per ADAPTER_GUIDE §4)
- [x] `on_message` remains `NotImplementedError` — not touched (US-9)

### Automated verification (2 related tests)

- [x] **Test 3 — `test_send_emits_valid_wire_payload`** **PASS**
      ```bash
      uv run pytest tests/channels/test_whatsapp.py::test_send_emits_valid_wire_payload -v
      ```
      Asserts: `messaging_product == "whatsapp"`, `to == OWNER_ID`,
      `type == "text"`, `text.body == "hi back"`, exactly one entry in `mock.send_log`

- [x] **Test 5 — `test_rate_limit_propagates_429`** **PASS**
      ```bash
      uv run pytest tests/channels/test_whatsapp.py::test_rate_limit_propagates_429 -v
      ```
      Asserts: when `mock.rate_limited = True`, `send()` returns a dict with
      `status == 429` or `error.code == 80007` (propagated from mock, not swallowed)

### Manual verification (optional, helper in isolation)

```bash
uv run python -c "
from glc.channels.envelope import ChannelReply
from glc.channels.catalogue.whatsapp.adapter import build_meta_send_payload
from tests.channels.mocks.whatsapp_mock import OWNER_ID

reply = ChannelReply(channel='whatsapp', channel_user_id=OWNER_ID, text='hi back')
print(build_meta_send_payload(reply))
"
```

Expected output:
```python
{'messaging_product': 'whatsapp', 'to': '919999990000', 'type': 'text', 'text': {'body': 'hi back'}}
```

### Quality gates

- [x] `ruff check glc/channels/catalogue/whatsapp/` → **All checks passed**
- [x] `mypy glc/channels/catalogue/whatsapp/` → **Success: no issues found in 5 source files**
- [ ] `check_pr_boundaries.py --base HEAD~1 --head HEAD` → run before opening mini-PR

### Commit

- [ ] Staged: `glc/channels/catalogue/whatsapp/adapter.py` + `help_docs/US5_build_meta_send_payload/`
- [ ] Committed: `US-5: build_meta_send_payload — Meta Graph API text send body + minimal send wiring`
- [ ] Push:
      ```bash
      git push -u origin feature/us5-build-meta-send-payload
      ```

### Mini-PR

- [ ] Open pull request inside the fork:
  - **base:** `integration`
  - **compare:** `feature/us5-build-meta-send-payload`
  - **title:** `US-5: build_meta_send_payload`
  - **body:** note both send tests pass; `on_message` unchanged
- [ ] Mini-PR approved and merged to `integration`

---

## Edge cases to be aware of

| Scenario | How it's handled |
|---|---|
| `reply.text` is `None` | Payload emits `"text": {"body": null}` — acceptable for US-5; US-10 may guard |
| Wrong `to` format (with `+` or `whatsapp:`) | Not normalized here — upstream pairing/parser must store bare E.164 |
| Flat `"text": "hello"` string | **Wrong shape** — fails Test 3 |
| `mock.rate_limited = True` | Mock returns 429 body; `send()` propagates it unchanged |
| No mock in config | `send()` returns the built dict (no HTTP) — US-10 adds real dispatch |

---

## Dependency map: where this function is consumed

```
US-5  build_meta_send_payload()
         │
         ├── Adapter.send()  — minimal wiring (mock dispatch for tests)
         │
         └── US-10  send() — outbound guard + provider dispatch + real Graph API POST
                      │
                      └── Tests 3, 5 (send structural tests)
```

US-10 cannot be started until US-5 and US-8 are merged to `integration`.
US-5 itself has zero predecessors.

---

## Quick reference: mock constants and send fields

From `tests/channels/mocks/whatsapp_mock.py`:

| Constant / field | Value | Maps to |
|---|---|---|
| `OWNER_ID` | `"919999990000"` | `reply.channel_user_id` in Test 3 |
| `mock.send_log[0]` | built payload | output of `build_meta_send_payload` |
| Rate-limit error code | `80007` | Meta OAuthException throttle code in mock |
