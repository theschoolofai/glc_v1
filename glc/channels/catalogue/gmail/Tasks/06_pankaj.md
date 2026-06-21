# STATUS: IMPLEMENTED — verify

## Who you are

- **Name:** Pankaj
- **Person:** 6
- **Role:** MIME body parser — text/plain and attachments

## Your job

Implement in `adapter.py`:

- `_extract_text_plain(self, msg) -> str`
- `_extract_attachments(self, msg) -> list[Attachment]`
- `_classify_attachment_kind(self, mime_type) -> Literal[...]`
- `_extract_email(self, addr: str) -> str`

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 6 (Pankaj): Email content parser`

## Do NOT edit

- Other persons' sections or test source files
- Do not redefine `ChannelMessage` / `Attachment` (use `glc.channels.envelope`)

## Depends on

- Person 5 — raw RFC 822 bytes parsed to email message elsewhere

## Wire format

Multipart emails contain both `text/plain` and `text/html`. **Surface only text/plain** in `ChannelMessage.text`.

Attachments: non-text parts with filename or `Content-Disposition: attachment` → store via `artifact_store()` → `Attachment(ref="art:...")`.

## Implementation spec

### `_extract_text_plain`

- Walk MIME parts; return first `text/plain` body
- Never return HTML content
- Return `""` if no plain part

### `_extract_attachments`

- Skip `text/plain`, `text/html`, multipart containers
- Persist bytes with `glc.channels.catalogue.gmail.artifacts.store`
- Map MIME to `Attachment.kind` via `_classify_attachment_kind`

### `_extract_email`

- `"Display Name <user@example.com>"` → `user@example.com`

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_channel_specific_behaviour_pubsub_to_text_plain` | `test_gmail_all.log` |

Must assert: plain text present, **no `<p>`** in `msg.text`.

```bash
uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```

## Acceptance checklist

- [ ] `text/plain` extracted, not `text/html`
- [ ] Attachments stored as `art:<hash>` refs
- [ ] Display names stripped from From header helper

## Suggested LLM prompt

```
Implement Person 6 methods in glc/channels/catalogue/gmail/adapter.py
(Pankaj: _extract_text_plain, _extract_attachments, _classify_attachment_kind, _extract_email).
Edit ONLY my section. Never surface HTML as ChannelMessage.text. Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```
