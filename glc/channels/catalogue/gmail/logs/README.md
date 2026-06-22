# Gmail adapter — pytest test logs

Saved pytest and lint output for Group 6 CI verification. Reference logs by **filename only** below.

| Test log file | Type | Contents | Result |
|---------------|------|----------|--------|
| `test_gmail_all.log` | Pytest test log | Full 7-test CI suite | 7 passed |
| `person1_sai_teja.log` | Pytest test log | Person 1 — mock injection + disconnect | 2 passed |
| `shwetha_send.log` | Pytest test log | Person 8 — outbound wire payload | 1 passed |
| `lint.log` | Static analysis | ruff + mypy on gmail adapter | clean |

## Regenerate

From the repo root:

```bash
uv run pytest tests/channels/test_gmail.py -v
```

Save stdout to the matching file under `logs/` if you need fresh test logs.

Person-specific runs:

```bash
uv run pytest tests/channels/test_gmail.py -v -k "owner_returns_valid_envelope or disconnect_is_handled"
uv run pytest tests/channels/test_gmail.py -v -k "send_emits_valid_wire_payload"
```
