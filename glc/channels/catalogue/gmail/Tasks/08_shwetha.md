# STATUS: COMPLETED — verify only

> **Do not rewrite this section unless a test fails.** Code is already in `adapter.py`.

## Who you are

- **Name:** Shwetha
- **Person:** 8
- **Role:** Outbound reply formatter — RFC 2822 MIME to Gmail `raw` field

## Your job

Implement (already done — verify) `_format_reply(self, reply: ChannelReply) -> str`.

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 8 (Shwetha): Reply formatter`

## Do NOT edit

- Other persons' sections or test source files
- Do not redefine `ChannelReply`

## Depends on

- Person 1 — `Adapter` skeleton

## Wire format

Gmail `users.messages.send` expects:

```json
{"raw": "<base64url-encoded RFC 822>", "threadId": "..."}
```

Build MIME with `email.message.EmailMessage`:

- `To` = `reply.channel_user_id`
- `From` = `os.getenv("GMAIL_BOT_ADDRESS", "me")`
- `Subject` = reply subject (e.g. `"Re: conversation"`)
- `In-Reply-To` / `References` from `reply.thread_id` when set
- Body = `reply.text`
- Encode: `base64.urlsafe_b64encode(bytes(msg)).decode().rstrip("=")`

Reference: https://developers.google.com/gmail/api/reference/rest/v1/users.messages/send

## Reference implementation

```python
def _format_reply(self, reply: ChannelReply) -> str:
    msg = EmailMessage()
    msg["To"] = reply.channel_user_id
    msg["From"] = os.getenv("GMAIL_BOT_ADDRESS", "me")
    msg["Subject"] = "Re: conversation"
    if reply.thread_id:
        msg["In-Reply-To"] = reply.thread_id
        msg["References"] = reply.thread_id
    msg.set_content(reply.text or "")
    raw_bytes = bytes(msg)
    return base64.urlsafe_b64encode(raw_bytes).decode().rstrip("=")
```

## Test logs

| Pytest test | Result | Log file |
|-------------|--------|----------|
| `test_send_emits_valid_wire_payload` | passed | `shwetha_send.log` |

Run:

```bash
uv run pytest tests/channels/test_gmail.py -v -k send_emits_valid_wire_payload
```

## Acceptance checklist

- [x] Output is base64url (no padding)
- [x] Decoded MIME contains `To:` and reply body text
- [x] Uses `ChannelReply` fields only (no hardcoded recipient)
- [x] Threading headers set when `thread_id` present

## Pending from you

**None** — task complete.

## Suggested LLM prompt

```
Verify _format_reply in glc/channels/catalogue/gmail/adapter.py
(Person 8 — Shwetha). Do NOT rewrite unless test_send_emits_valid_wire_payload fails.
Run: uv run pytest tests/channels/test_gmail.py -v -k send_emits_valid_wire_payload
Expected test log: shwetha_send.log (1 passed).
```
