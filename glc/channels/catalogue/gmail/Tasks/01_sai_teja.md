# STATUS: COMPLETED — verify only

> **Do not rewrite this section unless a test fails.** Code is already in `adapter.py`.

## Who you are

- **Name:** Sai Teja
- **Person:** 1
- **Role:** Adapter foundation — client protocol, class skeleton, OAuth wiring

## Your job

Implement (already done — verify) in `adapter.py`:

- `GmailClient` Protocol
- `Adapter` class: `name = "gmail"`, `__init__`, `_get_client()`
- `_LiveGmailClient` (module-level class at bottom of file)

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Sections:** `# Person 1 (Sai Teja)` (lines ~40–89 and ~456–492)

## Do NOT edit

- Other persons' sections in `adapter.py`
- `tests/channels/test_gmail.py`
- Group member list in `Docs/PR_DRAFT.md`
- Do not redefine `ChannelMessage` / `ChannelReply` (use `glc.channels.envelope`)

## Depends on

- Nothing — you are first in the build order. Everyone else depends on you.

## Wire format

Your `_LiveGmailClient` wraps the real Gmail REST API:

- `users.history.list(startHistoryId=...)`
- `users.messages.get(id, format="raw")`
- `users.messages.send(body={raw, threadId})`

Tests use `config["mock"]` instead — see `tests/channels/mocks/gmail_mock.py`.

## Implementation spec

### `GmailClient` Protocol

```python
def history_list(self, start_history_id: int) -> dict: ...
def messages_get(self, message_id: str) -> dict: ...
async def send(self, payload: dict) -> dict: ...
def pop_disconnect(self) -> bool: ...
```

### `__init__`

```python
def __init__(self, config: dict[str, Any] | None = None) -> None:
    super().__init__(config)
    self._client: GmailClient | None = self.config.get("client") or self.config.get("mock")
```

### `_get_client()`

- Return cached `self._client` if set (mock in tests).
- Otherwise load OAuth from `token.json` beside adapter, refresh if expired, build `googleapiclient` service, wrap in `_LiveGmailClient`.
- **No hardcoded credentials.**

### `_LiveGmailClient.pop_disconnect()`

- Always return `False` (only mock simulates disconnect).

## Reference implementation

Already in `adapter.py` under `# Person 1 (Sai Teja)` markers.

## Test logs

| Pytest test | Result | Log file |
|-------------|--------|----------|
| `test_on_message_owner_returns_valid_envelope` | passed | `person1_sai_teja.log` |
| `test_disconnect_is_handled` | passed | `person1_sai_teja.log` |

Run:

```bash
uv run pytest tests/channels/test_gmail.py -v -k "owner_returns_valid_envelope or disconnect_is_handled"
```

## Acceptance checklist

- [x] `config["mock"]` picked up in `__init__`
- [x] `_get_client()` caches client (no rebuild every message)
- [x] `_LiveGmailClient` matches `GmailClient` protocol
- [x] Live `pop_disconnect()` returns `False`
- [x] No credentials hardcoded in source
- [x] Section markers present

## Pending from you

**None** — task complete.

## Suggested LLM prompt

```
Review my assigned section in glc/channels/catalogue/gmail/adapter.py
(Person 1 — Sai Teja: GmailClient protocol, __init__, _get_client, _LiveGmailClient).
Do NOT rewrite unless a test fails. Confirm the acceptance checklist.
Run: uv run pytest tests/channels/test_gmail.py -v -k "owner_returns_valid_envelope or disconnect_is_handled"
Expected test log: person1_sai_teja.log (2 passed).
```
