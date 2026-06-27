# Contributing — Group Discord

This fork's job is one slot: **discord**, under `glc/channels/catalogue/discord/`.
The assignment is fixed by the instructors in the upstream repo's
[`GROUPS.md`](GROUPS.md) — there is no claim PR. Everything below is
how our team splits that one slot's work.

## Workflow

1. Read [`docs/ADAPTER_GUIDE.md`](docs/ADAPTER_GUIDE.md) and
   [`glc/channels/catalogue/discord/README.md`](glc/channels/catalogue/discord/README.md).
2. Read `tests/channels/test_discord.py` and
   `tests/channels/mocks/discord_mock.py`. **Do not edit either** —
   they're the fixed contract we're building against.
3. Implement `glc/channels/catalogue/discord/adapter.py` (and
   `schemas.py` if we need Discord-specific types).
4. Run the suite locally until all 7 tests pass:
   ```sh
   uv run pytest tests/channels/test_discord.py -v
   ```
5. Lint/type-check our owned path:
   ```sh
   uv run ruff check glc/channels/catalogue/discord
   uv run mypy glc/channels/catalogue/discord
   ```
6. Record the demo video — a real Discord bot exchange, not the mock.
7. Open the implementation PR using the repo's PR template. Keep the
   `# Group: group-discord` and `# Slot: discord` markers intact, list
   members, link the demo, describe wire-format quirks we hit.
8. CI runs boundary / test / scorecard checks; a CODEOWNER reviews
   before merge.

## Task breakdown by member

The codebase surface here is small — two files, seven tests — so a
10-way split means several members own a single test or a support
role (review, QA, docs) rather than an independent code path. Pair up
on `adapter.py` sections rather than working fully in isolation to
avoid merge conflicts inside one file.

  ┌─────┬────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┬──────────────────────────────────────────────────┐
  │  #  │ Member │                                                          Task                                                           │                      Files                       │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │     │ Member │ Read the contract surface — Study tests/channels/test_discord.py + tests/channels/mocks/discord_mock.py end-to-end.     │ tests/channels/test_discord.py,                  │
  │ 1   │  1     │ Write a short team summary of what each of the 7 tests expects (inputs, outputs, edge cases). Nothing to implement yet  │ tests/channels/mocks/discord_mock.py             │
  │     │        │ — understanding the mock is the prerequisite for everything else.                                                       │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ 2   │ Member │ Design schemas.py — Define Discord-specific Pydantic types (e.g. DiscordUser, DiscordMessage, DiscordEmbed) that the    │ glc/channels/catalogue/discord/schemas.py        │
  │     │  2     │ adapter will need internally. Cross-check against the Discord Gateway wire format cited in the mock's docstring.        │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ 3   │ Member │ Implement on_message — owner path (Test 1) — Parse a raw Discord Gateway MESSAGE_CREATE event and produce a valid       │ glc/channels/catalogue/discord/adapter.py        │
  │     │  3     │ ChannelMessage with trust_level = owner_paired. Must call glc.security.trust_level.classify().                          │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ 4   │ Member │ Implement on_message — stranger path (Test 2) — Ensure the same on_message classifies unknown senders as untrusted.     │ glc/channels/catalogue/discord/adapter.py        │
  │     │  4     │ Extend Member 3's work with the trust branching logic.                                                                  │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ 5   │ Member │ Implement send with correct wire payload (Test 3) — Implement send(ChannelReply) to build the Discord REST payload      │ glc/channels/catalogue/discord/adapter.py        │
  │     │  5     │ (channel_id + content/embeds) and dispatch it through config["mock"].send(body) in test mode or the real API otherwise. │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ 6   │ Member │ Handle forced disconnects (Test 4) — Add mock.pop_disconnect() check at the top of on_message so a forced disconnect    │ glc/channels/catalogue/discord/adapter.py        │
  │     │  6     │ returns a reconnect ChannelMessage cleanly instead of raising.                                                          │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ 7   │ Member │ Propagate rate-limit 429 (Test 5) — When Discord's API returns HTTP 429, propagate it as a structured 429 error to the  │ glc/channels/catalogue/discord/adapter.py        │
  │     │  7     │ caller. Do not swallow or retry silently.                                                                               │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │     │ Member │ Public-channel allowlist / mention-only filter (Test 6) — Read config["is_public_channel"] and                          │                                                  │
  │ 8   │  8     │ config["mention_only_in_public"]. In public channels, drop or mark untrusted any message from a non-paired sender who   │ glc/channels/catalogue/discord/adapter.py        │
  │     │        │ hasn't @-mentioned the bot.                                                                                             │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │     │ Member │ Mention resolution — behavioural test (Test 7) — Resolve <@user_id> tokens in content by calling                        │                                                  │
  │ 9   │  9     │ mock.get_user(user_id). Store the resolved usernames in ChannelMessage.metadata["mentions"]. This is the                │ glc/channels/catalogue/discord/adapter.py        │
  │     │        │ channel-specific behavioural test that proves the adapter understands Discord's actual wire format.                     │                                                  │
  ├─────┼────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │     │ Member │ CI green + PR submission — Run ruff check, ruff format, mypy, and pytest tests/channels/test_discord.py -v locally      │                                                  │
  │ 10  │  10    │ until all pass. Open the implementation PR using the template with # Group: Discord and # Slot: discord markers, a      │ .github/PULL_REQUEST_TEMPLATE.md, CI             │
  │     │        │ YouTube demo link, and the wire-quirks paragraph covering WebSocket heartbeats, embed handling, and mention-only mode.  │                                                  │
  └─────┴────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────┘

Adjust the names above to the actual people once assigned; the task
split stays the same regardless of who sits where.

## Shared rules (everyone)

- Stay inside `glc/channels/catalogue/discord/**`. The boundary check
  (`scripts/check_pr_boundaries.py`) fails the PR if the diff strays
  outside it.
- Never edit `tests/channels/test_discord.py` or
  `tests/channels/mocks/discord_mock.py`.
- No imports from LangChain, CrewAI, AutoGen, or Open Interpreter.
- `DISCORD_BOT_TOKEN` is an env var only — never commit it.

## Deadlines (IST)

| Milestone                    | Due                          |
|-------------------------------|-------------------------------|
| Implementation PR             | Wed 2026-07-01 23:59          |
| Demo video link in PR         | Thu 2026-07-02 23:59          |
| Review + scorecard window     | Fri 2026-07-03 → Sun 2026-07-05 |

Late policy: submissions accepted until the review window closes.
Resubmissions allowed.
