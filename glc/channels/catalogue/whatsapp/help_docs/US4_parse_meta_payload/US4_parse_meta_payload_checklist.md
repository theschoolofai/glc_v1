# US-4: parse_meta_payload — Strategy & Checklist

**Branch:** `feature/us4-parse-meta-payload`
**File to change:** `glc/channels/catalogue/whatsapp/adapter.py`
**Depends on:** nothing (Wave 1, fully parallel)
**Feeds into:** US-9 (`on_message` orchestrator)

---

## Strategy

### What US-4 delivers

A single module-level helper function in `adapter.py`:

```python
def parse_meta_payload(body: dict) -> dict[str, Any] | None:
```

It walks the Meta webhook JSON and returns a flat dict of extracted fields, or `None`
if the webhook carries no inbound message (e.g. delivery receipts, read receipts).

### JSON path walkthrough

`_text_webhook()` in the mock produces this shape (authoritative source — do not guess):

```
body
└── entry[0]
    └── changes[0]
        └── value
            ├── contacts[0].profile.name     → profile_name
            └── messages[0]
                ├── from                     → from_id
                ├── id                       → message_id
                ├── timestamp                → timestamp  (Unix epoch, string)
                ├── type                     → used to gate text extraction only
                └── text.body                → text  (only when type == "text")
```

The function navigates this path and returns:

```python
{
    "from_id":      msg["from"],          # str  — bare E.164, no "whatsapp:" prefix
    "text":         str | None,           # None when type != "text"
    "message_id":   msg["id"],            # str  — e.g. "wamid.HBgL101"
    "timestamp":    msg["timestamp"],     # str  — Unix epoch, US-9 converts to datetime
    "profile_name": str | None,           # None when contacts list is absent
}
```

### Full implementation

```python
def parse_meta_payload(body: dict) -> dict[str, Any] | None:
    try:
        value = body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        return None

    messages = value.get("messages")
    if not messages:
        return None

    msg = messages[0]
    contacts = value.get("contacts") or []
    profile_name = contacts[0].get("profile", {}).get("name") if contacts else None

    text: str | None = None
    if msg.get("type") == "text":
        text = msg.get("text", {}).get("body")

    return {
        "from_id": msg["from"],
        "text": text,
        "message_id": msg["id"],
        "timestamp": msg["timestamp"],
        "profile_name": profile_name,
    }
```

### Design decisions — each one is deliberate

**Return `None` on missing `messages` key (not an empty dict, not raise):**
Meta sends a delivery-status webhook for every message you send out, including
during the US-13 demo. These arrive with `value.statuses` but no `value.messages`.
Returning `None` lets US-9 silently skip them with a single `if parsed is None: return None`.

**Return `text=None` when `type != "text"` (not raise `KeyError`):**
`msg["text"]["body"]` doesn't exist for image, audio, reaction, sticker, etc.
The HANDOFF explicitly requires graceful handling here from day one. The `from`/`id`/
`timestamp`/profile fields populate normally — US-9 still builds a `ChannelMessage`
with `text=None` and `attachments=[]` so the agent knows a message arrived.

**`try/except (KeyError, IndexError)` on the outer navigation:**
If Meta ever sends a structurally malformed envelope (missing `entry`, empty
`changes`), the function returns `None` cleanly rather than crashing the adapter.
This is a narrow guard for structural failures, not a broad `except Exception`.

**`timestamp` stays as a raw string:**
The `ChannelMessage.arrived_at` field needs a `datetime`. Conversion belongs in US-9
(where UTC context exists), not inside this pure extraction function, which
has no reason to know the timezone convention. Keeps the function testable without
mocking `datetime`.

**`profile_name` can be `None`:**
`contacts` is not guaranteed on every Meta webhook variant. Guard with
`value.get("contacts") or []` (the `or []` handles both absent key and empty list).

### Placement decision

`parse_meta_payload` lives as a **module-level function** in `adapter.py`, NOT as a
method on `Adapter`. Same rationale as `verify_meta_signature` (US-3):
- Pure function (no `self`) — directly unit-testable without instantiating the adapter
- US-9 calls it internally; it does not need to be public API on the class
- HANDOFF §2.7 confirms helper placement is the team's choice

### What US-4 does NOT do

- Does NOT call `verify_meta_signature` — verification is always before parsing;
  sequencing is US-9's job
- Does NOT call `trust_level.classify()` — also US-9's job
- Does NOT touch `on_message` or `send` — those remain `NotImplementedError` stubs
- Does NOT convert `timestamp` to `datetime` — US-9 does that when constructing `ChannelMessage`
- Does NOT pass all 7 tests on its own — `on_message` (US-9) must be wired for that

### How the mock and function interlock

```
whatsapp_mock.py                              adapter.py
────────────────                              ──────────
_text_webhook(from_wa_id, text, ...)
  → builds entry[0].changes[0].value     ←→  parse_meta_payload(body):
    .messages[0].from = from_wa_id              value = body["entry"][0]...
    .messages[0].text.body = text               from_id = msg["from"]
    .contacts[0].profile.name = profile         text    = msg["text"]["body"]

queue_owner_message("hello")   → dict with OWNER_WA_ID,  text="hello"
queue_stranger_message("ping") → dict with STRANGER_WA_ID, text="ping"
```

### How US-9 will use this function (preview, implemented in US-9)

```python
# Inside on_message, after signature verified (Shape B) or directly (Shape A):
parsed = parse_meta_payload(decoded_body)
if parsed is None:
    return None   # delivery receipt — silently drop
trust = classify("whatsapp", parsed["from_id"])
...
return ChannelMessage(
    channel="whatsapp",
    channel_user_id=parsed["from_id"],
    user_handle=parsed["profile_name"] or parsed["from_id"],
    text=parsed["text"],
    trust_level=trust,
    arrived_at=datetime.utcfromtimestamp(int(parsed["timestamp"])),
    metadata={"provider": "meta", "message_id": parsed["message_id"]},
)
```

---

## Checklist

### Pre-flight

- [ ] Confirm active branch is `feature/us4-parse-meta-payload`
      ```bash
      git branch --show-current
      ```
- [ ] Confirm branch is based on `integration` (not `main`)
      ```bash
      git log --oneline integration..HEAD
      ```
- [ ] Re-read `_text_webhook()` in
      [whatsapp_mock.py](../../../../../../../tests/channels/mocks/whatsapp_mock.py)
      (lines 46–83) — this is the authoritative JSON shape `parse_meta_payload` must handle
- [ ] Re-read HANDOFF §7.4 (the two required edge cases)

### Implementation

- [ ] Open [adapter.py](../../../adapter.py)
- [ ] Add `from typing import Any` to imports if not already present
      (already imported in current stub — verify before adding again)
- [ ] Add `parse_meta_payload` as a **module-level function** directly after
      `verify_meta_signature` (before the `Adapter` class):
      ```python
      def parse_meta_payload(body: dict) -> dict[str, Any] | None:
          try:
              value = body["entry"][0]["changes"][0]["value"]
          except (KeyError, IndexError):
              return None

          messages = value.get("messages")
          if not messages:
              return None

          msg = messages[0]
          contacts = value.get("contacts") or []
          profile_name = contacts[0].get("profile", {}).get("name") if contacts else None

          text: str | None = None
          if msg.get("type") == "text":
              text = msg.get("text", {}).get("body")

          return {
              "from_id": msg["from"],
              "text": text,
              "message_id": msg["id"],
              "timestamp": msg["timestamp"],
              "profile_name": profile_name,
          }
      ```
- [ ] Function signature matches HANDOFF §7.4 spec:
  - Parameter: `body: dict`
  - Return: `dict[str, Any] | None`
- [ ] `on_message` and `send` remain `NotImplementedError` stubs — not touched

### Manual verification (4 required cases)

Run a quick Python REPL check from the repo root (`uv run python`):

```python
import sys; sys.path.insert(0, ".")
from glc.channels.catalogue.whatsapp.adapter import parse_meta_payload
from tests.channels.mocks.whatsapp_mock import WhatsappMock, OWNER_WA_ID, STRANGER_WA_ID

mock = WhatsappMock()
```

- [ ] **Case 1 — owner text message** → correct fields extracted
  ```python
  body = mock.queue_owner_message("hello")
  result = parse_meta_payload(body)
  assert result["from_id"] == OWNER_WA_ID        # "919999990000"
  assert result["text"] == "hello"
  assert result["profile_name"] == "owner"
  assert result["message_id"].startswith("wamid.")
  assert result["timestamp"] == "1700000000"
  print("Case 1 PASS:", result)
  ```

- [ ] **Case 2 — stranger text message** → correct fields extracted
  ```python
  body = mock.queue_stranger_message("ping")
  result = parse_meta_payload(body)
  assert result["from_id"] == STRANGER_WA_ID     # "917777770000"
  assert result["text"] == "ping"
  assert result["profile_name"] == "stranger"
  print("Case 2 PASS:", result)
  ```

- [ ] **Case 3 — delivery/status webhook (no `messages` key)** → `None`
  ```python
  status_webhook = {
      "object": "whatsapp_business_account",
      "entry": [{"changes": [{"field": "messages", "value": {
          "messaging_product": "whatsapp",
          "statuses": [{"id": "wamid.xyz", "status": "delivered", "timestamp": "1700000001"}]
      }}]}]
  }
  result = parse_meta_payload(status_webhook)
  assert result is None
  print("Case 3 PASS: None")
  ```

- [ ] **Case 4 — non-text message type (image)** → `text=None`, other fields present
  ```python
  image_webhook = {
      "object": "whatsapp_business_account",
      "entry": [{"changes": [{"field": "messages", "value": {
          "contacts": [{"profile": {"name": "sender"}, "wa_id": "911234567890"}],
          "messages": [{
              "from": "911234567890",
              "id": "wamid.img001",
              "timestamp": "1700000002",
              "type": "image",
              "image": {"id": "img_media_id", "mime_type": "image/jpeg"}
          }]
      }}]}]
  }
  result = parse_meta_payload(image_webhook)
  assert result is not None
  assert result["text"] is None
  assert result["from_id"] == "911234567890"
  assert result["profile_name"] == "sender"
  print("Case 4 PASS:", result)
  ```

### Quality gates

- [ ] `ruff check glc/channels/catalogue/whatsapp/` → **All checks passed**
- [ ] `mypy glc/channels/catalogue/whatsapp/` → **Success: no issues found**
- [ ] `check_pr_boundaries.py --base integration --head HEAD` → **OK: all files inside owned paths**
      ```bash
      uv run python scripts/check_pr_boundaries.py --base integration --head HEAD --group "Group WhatsApp"
      ```
      *(Use `--base integration`, not `--base main` — the fork has no local `main` branch)*

### Commit

- [ ] Stage only owned files:
      ```bash
      git add glc/channels/catalogue/whatsapp/adapter.py
      git add "glc/channels/catalogue/whatsapp/help_docs/US4_parse_meta_payload/"
      ```
- [ ] Commit:
      ```bash
      git commit -m "US-4: parse_meta_payload — walk entry/changes/value, None on status webhooks, text=None on non-text types"
      ```
- [ ] Push:
      ```bash
      git push -u origin feature/us4-parse-meta-payload
      ```

### Mini-PR

- [ ] Open pull request inside the fork:
  - **base:** `integration`
  - **compare:** `feature/us4-parse-meta-payload`
  - **title:** `US-4: parse_meta_payload`
  - **body:** document all 4 manual verification cases and their results
- [ ] PR description confirms: no `on_message` changes, no hardcoded secrets, all 4 cases verified manually
- [ ] Mini-PR approved and merged to `integration`

---

## Edge cases to be aware of (already handled by the implementation above)

| Scenario | How it's handled |
|---|---|
| `messages` key absent (delivery receipt, read receipt) | `value.get("messages")` → falsy → `return None` |
| `messages` key present but empty list | `if not messages` catches `[]` → `return None` |
| `type == "image"` / `"audio"` / `"sticker"` / `"reaction"` | `if msg.get("type") == "text"` gate → `text = None` |
| `contacts` key absent entirely | `value.get("contacts") or []` → `profile_name = None` |
| `contacts[0]` has no `profile` key | `.get("profile", {}).get("name")` → `None` |
| `entry` missing or `changes` missing | `try/except (KeyError, IndexError)` → `return None` |
| `messages[0]` missing `from` or `id` | Propagates `KeyError` — structurally invalid; Meta guarantees these fields exist |
| `timestamp` is a string, not an int | Intentional — returned as-is; US-9 calls `int(parsed["timestamp"])` before `datetime.utcfromtimestamp()` |

---

## Dependency map: where this function is consumed

```
US-4  parse_meta_payload()
         │
         └── US-9  on_message() — after verify_meta_signature() passes (Shape B)
                      │           or directly on bare dict (Shape A)
                      │           returns None → on_message returns None (skip)
                      │           returns dict → classify + allowlist + ChannelMessage
                      │
                      └── Tests 1, 2, 4, 6 (Shape A — bare dict, signature pre-verified)
                          Test 7             (Shape B — verify first, then parse)
```

US-9 cannot be started until US-3, US-4, US-6, and US-7 are all merged to `integration`.
US-4 itself has zero predecessors.

---

## Quick reference: mock constants and JSON fields

From `tests/channels/mocks/whatsapp_mock.py`:

| Constant | Value | Maps to |
|---|---|---|
| `OWNER_WA_ID` | `"919999990000"` | `result["from_id"]` for owner messages |
| `STRANGER_WA_ID` | `"917777770000"` | `result["from_id"]` for stranger messages |
| `PHONE_NUMBER_ID` | `"10987654321"` | `value.metadata.phone_number_id` (not extracted by US-4) |
| `DEFAULT_APP_SECRET` | `"test-app-secret"` | Used by US-3, not US-4 |
| `message_id` default | `"wamid.HBgL"` | `result["message_id"]` prefix |
| `timestamp` default | `"1700000000"` | `result["timestamp"]` |
