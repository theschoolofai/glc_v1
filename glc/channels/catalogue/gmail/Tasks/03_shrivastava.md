# STATUS: COMPLETED — verify only

> **Do not rewrite this section unless a test fails.** Code is already in `adapter.py`.

## Who you are

- **Name:** Shrivastava
- **Person:** 3
- **Role:** Pub/Sub push envelope parser

## Your job

Implement `_parse_pubsub_envelope(self, raw: dict[str, Any]) -> tuple[str, int]` in `adapter.py`.

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 3 (Shrivastava): Pub/Sub envelope parser`

## Do NOT edit

- Other persons' sections
- `tests/channels/test_gmail.py`
- Do not redefine `ChannelMessage` / `ChannelReply`

## Depends on

- Person 1 (Sai Teja) — `Adapter` skeleton must exist

## Wire format

Gmail Pub/Sub push body:

```json
{
  "message": {
    "data": "<base64 of {\"emailAddress\":\"...\",\"historyId\":N}>"
  }
}
```

Use Pydantic types from `schemas.py`: `PubSubPushNotification`, `PubSubMessageData`.

Reference: https://developers.google.com/gmail/api/guides/push

## Implementation spec

```python
def _parse_pubsub_envelope(self, raw: dict[str, Any]) -> tuple[str, int]:
```

1. Validate with `PubSubPushNotification(**raw)`
2. `base64.b64decode(notification.message.data)` → JSON
3. Parse with `PubSubMessageData`
4. Return `(emailAddress, historyId)`
5. Raise `ValueError` on malformed input

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_channel_specific_behaviour_pubsub_to_text_plain` (step 1) | `test_gmail_all.log` |

Run:

```bash
uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```

## Acceptance checklist

- [x] Returns `(str, int)` for valid Pub/Sub push
- [x] Raises `ValueError` on malformed envelope
- [x] Uses `schemas.py` types (not ad-hoc dict access only)

## Pending from you

**None** — task complete.

## Suggested LLM prompt

```
Implement _parse_pubsub_envelope in glc/channels/catalogue/gmail/adapter.py
(Person 3 — Shrivastava). Edit ONLY my section. Use PubSubPushNotification and
PubSubMessageData from schemas.py. Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```
