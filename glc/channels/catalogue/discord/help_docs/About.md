
About This Project

  GLC v1 (Gateway for LLMs and Channels) is the Session 11 deliverable for The School of AI course. It's a secure LLM
  gateway (port 8111) that:

  - Extends the V9 LLM gateway (chat, vision, embeddings, cost ledger, routing)
  - Adds a channel + voice layer — typed adapters that bridge messaging platforms (Discord, Telegram, Slack, etc.) and
  voice providers (STT/TTS) to an agent runtime
  - Enforces six security architectural moves (trust levels, out-of-band kill switch, append-only audit log, policy
  engine outside LLM context, etc.)

  Your group (Group Discord / G2) must implement the Discord adapter stub at glc/channels/catalogue/discord/ and pass
  all 7 tests in tests/channels/test_discord.py.

  ---
  10 Tasks — One Per Team Member

  #: 1
  Member: Member 1
  Task: Read the contract surface — Study tests/channels/test_discord.py + tests/channels/mocks/discord_mock.py
    end-to-end. Write a short team summary of what each of the 7 tests expects (inputs, outputs, edge cases). Nothing to

    implement yet — understanding the mock is the prerequisite for everything else.
  Files: tests/channels/test_discord.py, tests/channels/mocks/discord_mock.py
  ────────────────────────────────────────
  #: 2
  Member: Member 2
  Task: Design schemas.py — Define Discord-specific Pydantic types (e.g. DiscordUser, DiscordMessage, DiscordEmbed) that

    the adapter will need internally. Cross-check against the Discord Gateway wire format cited in the mock's docstring.
  Files: glc/channels/catalogue/discord/schemas.py
  ────────────────────────────────────────
  #: 3
  Member: Member 3
  Task: Implement on_message — owner path (Test 1) — Parse a raw Discord Gateway MESSAGE_CREATE event and produce a
  valid
    ChannelMessage with trust_level = owner_paired. Must call glc.security.trust_level.classify().
  Files: glc/channels/catalogue/discord/adapter.py
  ────────────────────────────────────────
  #: 4
  Member: Member 4
  Task: Implement on_message — stranger path (Test 2) — Ensure the same on_message classifies unknown senders as
    untrusted. Extend Member 3's work with the trust branching logic.
  Files: glc/channels/catalogue/discord/adapter.py
  ────────────────────────────────────────
  #: 5
  Member: Member 5
  Task: Implement send with correct wire payload (Test 3) — Implement send(ChannelReply) to build the Discord REST
    payload (channel_id + content/embeds) and dispatch it through config["mock"].send(body) in test mode or the real API

    otherwise.
  Files: glc/channels/catalogue/discord/adapter.py
  ────────────────────────────────────────
  #: 6
  Member: Member 6
  Task: Handle forced disconnects (Test 4) — Add mock.pop_disconnect() check at the top of on_message so a forced
    disconnect returns a reconnect ChannelMessage cleanly instead of raising.
  Files: glc/channels/catalogue/discord/adapter.py
  ────────────────────────────────────────
  #: 7
  Member: Member 7
  Task: Propagate rate-limit 429 (Test 5) — When Discord's API returns HTTP 429, propagate it as a structured 429 error
    to the caller. Do not swallow or retry silently.
  Files: glc/channels/catalogue/discord/adapter.py
  ────────────────────────────────────────
  #: 8
  Member: Member 8
  Task: Public-channel allowlist / mention-only filter (Test 6) — Read config["is_public_channel"] and
    config["mention_only_in_public"]. In public channels, drop or mark untrusted any message from a non-paired sender
  who
  ────────────────────────────────────────
  Member: Member 7
  Task: Propagate rate-limit 429 (Test 5) — When Discord's API returns HTTP 429, propagate it as a structured 429 error to the caller. Do
  ---
  10 Tasks — One Per Team Member

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

  ---
  Key constraint: your PR may only touch files under glc/channels/catalogue/discord/ — the boundary CI check (scripts/check_pr_boundaries.py) will fail any diff that strays outside those paths.