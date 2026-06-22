# STATUS: IMPLEMENTED — verify

## Who you are

- **Name:** Nitha
- **Person:** 5
- **Role:** Fetch raw RFC 822 message bytes from Gmail API

## Your job

Implement `_fetch_message(self, message_id: str, client: GmailClient) -> bytes | None`.

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 5 (Nitha): Message fetcher`

## Do NOT edit

- Other persons' sections or test source files

## Depends on

- Person 1 — `GmailClient.messages_get`
- Person 4 — message IDs from history

## Wire format

`client.messages_get(message_id)` returns `{"raw": "<base64url-rfc822-no-padding>"}`.

Gmail uses **base64url without padding** — add `"=" * (-len(raw_b64) % 4)` before decode.

Reference: https://developers.google.com/gmail/api/reference/rest/v1/users.messages/get

## Implementation spec

- Return decoded RFC 822 bytes, or `None` if missing/not found
- Catch `KeyError` from mock when message unknown; log warning

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_channel_specific_behaviour_pubsub_to_text_plain` (steps 3–4) | `test_gmail_all.log` |

```bash
uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```

## Acceptance checklist

- [ ] Base64url padding handled correctly
- [ ] Returns `None` on missing message (no unhandled exception)

## Suggested LLM prompt

```
Implement _fetch_message in glc/channels/catalogue/gmail/adapter.py
(Person 5 — Nitha). Edit ONLY my section. Handle base64url padding. Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```
