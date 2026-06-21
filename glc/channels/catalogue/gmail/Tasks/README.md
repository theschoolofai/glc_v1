# Gmail Group 6 — Task Index

Per-person LLM task specs for the Gmail channel adapter. Each teammate opens **only their file**, pastes it into an LLM with `adapter.py`, and implements (or verifies) their section.

See also: `Docs/ADAPTER_GUIDE.md` (Session 11 workflow) and `logs/README.md` (pytest test logs).

**Note:** Person 2 is not assigned (numbering jumps 1 → 3). `schemas.py` is shared infrastructure — do not redefine `ChannelMessage` / `ChannelReply`.

## Status

| Person | Name | Task file | Primary methods | Primary pytest test(s) | Status |
|--------|------|-----------|-----------------|------------------------|--------|
| 1 | Sai Teja | `01_sai_teja.md` | `GmailClient`, `__init__`, `_get_client`, `_LiveGmailClient` | `test_on_message_owner_returns_valid_envelope`, `test_disconnect_is_handled` | **COMPLETED** |
| 3 | Shrivastava | `03_shrivastava.md` | `_parse_pubsub_envelope` | `test_channel_specific_behaviour_pubsub_to_text_plain` | IMPLEMENTED — verify |
| 4 | Harapanahalli | `04_harapanahalli.md` | `_fetch_history` | `test_channel_specific_behaviour_pubsub_to_text_plain` | IMPLEMENTED — verify |
| 5 | Nitha | `05_nitha.md` | `_fetch_message` | `test_channel_specific_behaviour_pubsub_to_text_plain` | IMPLEMENTED — verify |
| 6 | Pankaj | `06_pankaj.md` | `_extract_text_plain`, `_extract_attachments`, helpers | `test_channel_specific_behaviour_pubsub_to_text_plain` | IMPLEMENTED — verify |
| 7 | Shrey | `07_shrey.md` | `on_message`, `on_messages` | tests 1, 2, 6, 7 | IMPLEMENTED — verify |
| 8 | Shwetha | `08_shwetha.md` | `_format_reply` | `test_send_emits_valid_wire_payload` | **COMPLETED** |
| 9 | Rajan | `09_rajan.md` | `send` | `test_send_emits_valid_wire_payload`, `test_rate_limit_propagates_429` | IMPLEMENTED — verify |
| 10 | Vishy | `10_vishy.md` | `_resolve_trust_level`, `_check_allowlist`, `_handle_rate_limit` | tests 1, 2, 4, 5, 6 | IMPLEMENTED — verify |

## Build order

Implement (or verify) in this order so dependencies exist:

**1 → 3 → 4 → 5 → 6 → 10 → 7 → 8 → 9**

## How to use with an LLM

1. Open **your** numbered task file only.
2. Copy the **Suggested LLM prompt** at the bottom.
3. Attach `adapter.py` as read-only context — **do not modify test source files**.
4. Run the pytest command listed in your file.
5. Attach the matching **test log filename** from `logs/` if sharing proof (e.g. `person1_sai_teja.log`).

All 7 CI tests must pass before the group PR merges:

```bash
uv run pytest tests/channels/test_gmail.py -v
```

Save output to `logs/test_gmail_all.log` if refreshing test logs.

## Test logs

| Test log file | Pytest scope |
|---------------|--------------|
| `test_gmail_all.log` | All 7 CI tests |
| `person1_sai_teja.log` | Person 1 |
| `shwetha_send.log` | Person 8 |
| `lint.log` | ruff + mypy (not pytest) |

See `logs/README.md` for details.
