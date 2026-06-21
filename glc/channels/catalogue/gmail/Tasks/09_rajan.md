# STATUS: IMPLEMENTED — verify

## Who you are

- **Name:** Rajan
- **Person:** 9
- **Role:** Outbound send — Gmail API integration

## Your job

Implement `async def send(self, reply: ChannelReply) -> Any`.

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 9 (Rajan): send() — Gmail send API integration`

## Do NOT edit

- Other persons' sections or test source files
- Person 8's `_format_reply` (call it, don't rewrite)

## Depends on

- Person 1 — `_get_client()`
- Person 8 — `_format_reply(reply)`
- Person 10 — `_handle_rate_limit(result)`

## Implementation spec

```python
async def send(self, reply: ChannelReply) -> Any:
    raw = self._format_reply(reply)
    send_payload = GmailSendPayload(raw=raw, threadId=reply.thread_id)
    payload = send_payload.model_dump(exclude_none=True)
    client = self._get_client()
    result = await client.send(payload)
    self._handle_rate_limit(result)
    return result  # return unchanged — do not swallow 429
```

Use `GmailSendPayload` from `schemas.py`.

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_send_emits_valid_wire_payload` | `shwetha_send.log` / `test_gmail_all.log` |
| `test_rate_limit_propagates_429` | `test_gmail_all.log` |

```bash
uv run pytest tests/channels/test_gmail.py -v -k "send_emits_valid_wire_payload or rate_limit_propagates_429"
```

## Acceptance checklist

- [ ] Calls `_format_reply` then `client.send`
- [ ] Payload has `raw` key (base64url MIME)
- [ ] 429 response returned to caller (not swallowed)

## Suggested LLM prompt

```
Implement send() in glc/channels/catalogue/gmail/adapter.py (Person 9 — Rajan).
Call _format_reply, build GmailSendPayload, await client.send, call _handle_rate_limit.
Return result unchanged. Edit ONLY my section. Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k "send_emits_valid_wire_payload or rate_limit"
```
