# STATUS: COMPLETED — verify only

> **Do not rewrite this section unless a test fails.** Code is already in `adapter.py`.

## Who you are

- **Name:** Vishy
- **Person:** 10
- **Role:** Trust classification, allowlist, rate-limit observability

## Your job

Implement in `adapter.py`:

- `_resolve_trust_level(self, sender_email: str) -> TrustLevel`
- `_check_allowlist(self, sender_email: str, trust_level: str) -> bool`
- `_handle_rate_limit(self, response: Any) -> None`

Also consumed by Person 7's `on_message` (disconnect + public-channel drop).

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 10 (Vishy): Trust level + error handling helpers`

## Do NOT edit

- Other persons' sections or test source files
- Must use `glc.security.trust_level.classify` — do not invent trust logic

## Depends on

- Person 1 — client with `pop_disconnect()`

## Implementation spec

### `_resolve_trust_level`

```python
return classify("gmail", sender_email)
```

Must run **before** constructing `ChannelMessage` (Person 7 calls this).

### `_check_allowlist`

- Return `True` for `owner_paired` / `user_paired`
- Return `False` for `untrusted`

### `_handle_rate_limit`

- If response dict has `status == 429` or `error.code == 429`, log warning
- **Do NOT catch or transform** — caller must receive 429 dict (test 5)

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_on_message_owner_returns_valid_envelope` | `person1_sai_teja.log` / `test_gmail_all.log` |
| `test_on_message_stranger_is_untrusted` | `test_gmail_all.log` |
| `test_allowlist_silently_drops_stranger_in_public` | `test_gmail_all.log` |
| `test_rate_limit_propagates_429` | `test_gmail_all.log` |
| `test_disconnect_is_handled` | `person1_sai_teja.log` |

```bash
uv run pytest tests/channels/test_gmail.py -v -k "owner_returns_valid_envelope or stranger_is_untrusted or allowlist or rate_limit or disconnect"
```

## Acceptance checklist

- [x] Uses `classify("gmail", sender_email)`
- [x] Public channel: untrusted senders dropped in orchestrator
- [x] 429 propagated to `send()` caller
- [x] Disconnect via `pop_disconnect()` does not raise

## Pending from you

**None** — task complete.

## Suggested LLM prompt

```
Implement Person 10 helpers in glc/channels/catalogue/gmail/adapter.py (Vishy:
_resolve_trust_level, _check_allowlist, _handle_rate_limit). Use classify() from
glc.security.trust_level. Do not swallow 429. Edit ONLY my section. Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k "stranger_is_untrusted or rate_limit or disconnect"
```
