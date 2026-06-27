# STATUS: COMPLETED — verify only

> **Do not rewrite this section unless a test fails.** Code is already in `adapter.py`.

## Who you are

- **Name:** Shrey
- **Person:** 7
- **Role:** Inbound orchestrator — wire Pub/Sub push to `ChannelMessage`

## Your job

Implement:

- `async def on_message(self, raw) -> ChannelMessage | None`
- `async def on_messages(self, raw) -> list[ChannelMessage]` (batch variant)

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 7 (Shrey): on_message() — main orchestrator`

## Do NOT edit

- Other persons' sections or test source files

## Depends on

- Persons 1, 3, 4, 5, 6, 10 must exist before you wire the pipeline

## Orchestration flow

1. `client = self._get_client()`
2. If `client.pop_disconnect()` → return `None` (or `[]` for batch)
3. `_parse_pubsub_envelope(raw)` → history_id
4. `_fetch_history(history_id, client)` → message IDs
5. `_fetch_message(msg_id, client)` → raw bytes
6. Parse RFC 822; `_extract_email` on From
7. `_resolve_trust_level(from_addr)`
8. If `config["is_public_channel"]` and untrusted → return `None`
9. `_extract_text_plain` + `_extract_attachments`
10. Return `ChannelMessage(channel="gmail", ..., trust_level=..., arrived_at=datetime.now(UTC))`

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_on_message_owner_returns_valid_envelope` | `test_gmail_all.log` |
| `test_on_message_stranger_is_untrusted` | `test_gmail_all.log` |
| `test_allowlist_silently_drops_stranger_in_public` | `test_gmail_all.log` |
| `test_channel_specific_behaviour_pubsub_to_text_plain` | `test_gmail_all.log` |

```bash
uv run pytest tests/channels/test_gmail.py -v -k "owner_returns_valid_envelope or stranger_is_untrusted or allowlist or pubsub_to_text_plain"
```

## Acceptance checklist

- [x] Returns valid `ChannelMessage` for owner (trust `owner_paired`)
- [x] Strangers get `untrusted` tag (not dropped unless public channel)
- [x] Public channel drops untrusted (`None`)
- [x] Full Pub/Sub → text/plain pipeline works

## Pending from you

**None** — task complete.

## Suggested LLM prompt

```
Implement on_message and on_messages in glc/channels/catalogue/gmail/adapter.py
(Person 7 — Shrey). Wire together Person 3–6 and Person 10 helpers. Edit ONLY my section.
Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k "owner_returns_valid_envelope or pubsub_to_text_plain"
```
