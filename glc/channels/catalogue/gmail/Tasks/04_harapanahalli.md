# STATUS: IMPLEMENTED — verify

## Who you are

- **Name:** Harapanahalli
- **Person:** 4
- **Role:** Gmail History API — discover new message IDs

## Your job

Implement `_fetch_history(self, history_id: int, client: GmailClient) -> list[tuple[str, str | None]]`.

## Where to edit

- **File:** `glc/channels/catalogue/gmail/adapter.py`
- **Section:** `# Person 4 (Harapanahalli): Gmail History API client`

## Do NOT edit

- Other persons' sections or test source files

## Depends on

- Person 1 — `GmailClient.history_list`
- Person 3 — `history_id` from Pub/Sub envelope

## Wire format

Call `client.history_list(history_id)`. Response shape:

```json
{
  "history": [{
    "messagesAdded": [{"message": {"id": "...", "threadId": "..."}}]
  }]
}
```

Reference: https://developers.google.com/gmail/api/reference/rest/v1/users.history/list

## Implementation spec

Walk `history[].messagesAdded[].message`; collect `(id, threadId)` tuples.

## Test logs

| Pytest test | Log file |
|-------------|----------|
| `test_channel_specific_behaviour_pubsub_to_text_plain` (step 2) | `test_gmail_all.log` |

```bash
uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```

## Acceptance checklist

- [ ] Calls `client.history_list(history_id)`
- [ ] Returns list of `(message_id, thread_id)` tuples
- [ ] Handles empty history gracefully (empty list)

## Suggested LLM prompt

```
Implement _fetch_history in glc/channels/catalogue/gmail/adapter.py
(Person 4 — Harapanahalli). Edit ONLY my section. Do not modify test files.
Run: uv run pytest tests/channels/test_gmail.py -v -k pubsub_to_text_plain
```
