# Discord Gateway adapter — `feat/mkthoma-discord-demo`

Slot `discord` (group **Discord**, chat `G2`). This README scopes what **this
feature branch** commits and what is still outstanding.

This branch is an **incremental** step: it adds the Discord wire-format
**schemas only**. `adapter.py` is still the maintainer-provided stub —
implementing it (and making the 7-test rubric pass) is the next step, not part
of this commit.

## What this branch does

One file inside the slot's owned path (`glc/channels/catalogue/discord/`):

### `schemas.py` — Discord wire-format types

Pydantic models for the frames the adapter will consume and produce — they
model the `MESSAGE_CREATE` gateway frame and the create-message REST body:

- `DiscordUser`, `DiscordMessage`, `DiscordGatewayEvent` — **inbound**, with
  `extra="ignore"` so Discord's evolving / multiplexed payloads don't crash
  parsing.
- `DiscordCreateMessageBody` — **outbound** REST body, with `extra="forbid"`
  and `tts` defaulting to `False` (the bot never speaks unprompted).
- Snowflake ids are kept as strings, never coerced to int.

The canonical `ChannelMessage` / `ChannelReply` envelope is **not** redefined
here — it lives in `glc.channels.envelope`.

### Verification

Run from the repo root (`C:\Users\akenn\GitHub\glc_v1_g2_discord`):

```powershell
uv run ruff check glc/channels/catalogue/discord/  # All checks passed!
uv run mypy  glc/channels/catalogue/discord/       # no issues found
```

> **Note:** `uv run pytest tests/channels/test_discord.py` does **not** pass yet.
> The 7 tests exercise the adapter, which is still a stub (`raise
> NotImplementedError`). `schemas.py` imports and type-checks cleanly on its own;
> the suite goes green only once `adapter.py` is implemented (below).

## What still needs to be done

- [ ] **Implement `adapter.py`** — `on_message` + `send`, subclassing
  `glc.channels.base.ChannelAdapter`. This is what turns the 7-test rubric green:
  lazy gateway-frame parsing, `trust_level` stamped via
  `glc.security.trust_level.classify` before the envelope is built, the public-
  channel allowlist gate via `glc.security.allowlists.allowed`, `<@id>` mention
  resolution via the client's `get_user`, graceful forced-disconnect handling,
  and 429 passthrough on `send`. Currently raises `NotImplementedError`.
- [ ] **Demo video (required by the PR template).** Record a real upstream
  Discord message handled end to end — the tests only exercise the in-memory
  mock. Needs a real bot token (`DISCORD_BOT_TOKEN` with the **MESSAGE_CONTENT**
  privileged intent) and the live Gateway/REST path.
- [ ] **PR body.** Fill in the group **members** line and the **demo link**, and
  add the short "wire-format quirks you hit" note. Keep the
  `# Group: Discord` / `# Slot: discord` markers intact.
- [ ] **Tidy `__init__.py`.** Its docstring still reads `"Discord Gateway
  adapter (stub)."` — drop "(stub)" once the adapter is implemented.

## Out of scope for this branch

- The shared envelope, trust, pairing, and allowlist modules (`glc.channels.*`,
  `glc.security.*`) — already in `main` and owned by the maintainers; editing
  them would fail the boundary check.
- The test and mock files (`tests/channels/test_discord.py`,
  `tests/channels/mocks/discord_mock.py`) — fixed contract, do not edit.
