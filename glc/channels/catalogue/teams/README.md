# Teams Channel Adapter

Group 15 — Slot `teams` — Session 11 (GLC v1).

## Architecture

The adapter sits between the GLC gateway and the Microsoft Bot Framework Connector Service. Inbound HTTP POST requests from Teams (via the Connector) arrive as **Bot Framework Activity** objects; the adapter normalises them into the channel-agnostic `ChannelMessage` envelope and hands it up. Outbound replies go the reverse way: the adapter receives a `ChannelReply`, constructs a Bot Framework `message` Activity body, and POSTs it back to the Connector using an OAuth 2.0 bearer token.

```
Teams client
    │  (HTTPS)
Bot Framework Connector Service
    │  POST /api/messages  (Activity JSON)
GLC gateway → TeamsAdapter.on_message()
                  │
                  ├─ classify trust level
                  ├─ apply public-channel allowlist
                  ├─ extract Adaptive Card text
                  └─ return ChannelMessage
                              │
                          agent logic
                              │
                          ChannelReply
                              │
              TeamsAdapter.send()
                  │
                  ├─ look up cached serviceUrl / conversation_id
                  ├─ fetch OAuth token (client-credentials)
                  └─ POST Activity to Connector
```

Two files implement the slot:

| File | Purpose |
|---|---|
| `adapter.py` | `Adapter` subclass — `on_message`, `send`, helpers |
| `schemas.py` | `ADAPTIVE_CARD_CONTENT_TYPE` constant |

## Teams-specific quirks

### Azure AD registration and OAuth token exchange

Every outbound reply must carry a Bearer token obtained via the **client-credentials flow** against the single-tenant Azure AD token endpoint:

```
POST https://login.microsoftonline.com/{TEAMS_TENANT_ID}/oauth2/v2.0/token
scope=https://api.botframework.com/.default
```

Required env vars: `TEAMS_APP_ID`, `TEAMS_APP_PASSWORD`, `TEAMS_TENANT_ID`.

> **Note:** Microsoft stopped allowing new *multi-tenant* bot registrations after 2025-07-31. The adapter intentionally targets the single-tenant endpoint. Do not "fix" it back to the deprecated `botframework.com` multi-tenant path.

Tokens are cached in `_TOKEN_CACHE` (keyed by `TEAMS_APP_ID`, with a 60-second early-expiry guard) to avoid a round-trip on every send.

### `serviceUrl` caching

The Connector hands the adapter a **per-conversation, dynamic** `serviceUrl` on every inbound Activity. The channel-agnostic `ChannelReply` envelope has no field for this URL, so `on_message` writes it (along with `conversation_id`) into `self._contexts[from_id]`, and `send` reads it back. If `send` is called for a user whose context has never been populated by `on_message`, it raises `RuntimeError` — there is no safe default URL to guess.

### Adaptive Cards

Users can submit form-like interactions via Adaptive Cards. These arrive as an `attachments[]` entry with `contentType == application/vnd.microsoft.card.adaptive` rather than as plain `text`. The adapter:

1. Walks the card's `body` breadth-first to find the first `TextBlock` with a non-empty `text` field and promotes it to `ChannelMessage.text`.
2. Stores the raw card JSON under `metadata["adaptive_card"]` so downstream logic can re-render or inspect it.

Adapters that ignore `attachments` lose the user's intent entirely when a card-form interaction is submitted.

### Public-channel allowlist gating

Teams bots receive *every* message in a channel they're installed in, not just messages directed at them. When `config["is_public_channel"]` is `True`, the adapter calls `glc.security.allowlists.allowed()` and silently returns `None` for any message that doesn't pass the check (typically: stranger, not @-mentioned). This prevents the agent from triggering on every unrelated conversation that flows through a busy team channel.

### Disconnect handling

The Bot Framework Connector can drop the underlying connection mid-session. `on_message` detects a forced-disconnect signal from the mock (or from the real Connector's absence) and returns `None` rather than raising — allowing the GLC gateway to reconnect and keep serving subsequent events.

## How the tests exercise the trust boundary

`tests/channels/test_teams.py` uses `TeamsMock` (at `tests/channels/mocks/teams_mock.py`) as the contract surface. The mock is fixed; the adapter must satisfy it, not the reverse.

| Test | What it checks |
|---|---|
| `test_on_message_owner_returns_valid_envelope` | A paired owner gets `trust_level == "owner_paired"` and all envelope fields populated. |
| `test_on_message_stranger_is_untrusted` | An unrecognised sender gets `trust_level == "untrusted"` but is **not** dropped in a private/DM context. |
| `test_send_emits_valid_wire_payload` | Outbound body has `type: "message"`, correct `text`, and `replyToId` set to the inbound activity id. |
| `test_disconnect_is_handled` | `on_message` must not raise when the mock signals a forced disconnect; it returns `None`. |
| `test_rate_limit_propagates_429` | When the mock returns HTTP 429, `send` propagates the status to the caller as `{"status": 429}`. |
| `test_allowlist_silently_drops_stranger_in_public` | In a public-channel context a stranger's message produces `None` (silently dropped). |
| `test_channel_specific_behaviour_adaptive_card` | An Adaptive Card's first TextBlock text lands in `msg.text`; the raw card is at `msg.metadata["adaptive_card"]`. |

The trust boundary is exercised across three tests: owner (`owner_paired`), stranger in DM (`untrusted` but delivered), and stranger in public channel (`None` — dropped before trust classification matters). Together they confirm that trust level and allowlist gating are orthogonal concerns applied in the right order.

## Local demo (Bot Framework Emulator)

The `setup/` folder contains two scripts for running and configuring the adapter locally without a deployed GLC gateway or Azure Bot resource.

### Files

| File | Purpose |
|---|---|
| `setup/emulator_runner.py` | FastAPI bridge between the Emulator and the real adapter |
| `setup/trust_setup.py` | CLI to set trust level for the Emulator user |

### Start the server

```bash
# From repo root (Python ≥ 3.11)
uv run python glc/channels/catalogue/teams/setup/emulator_runner.py
# Listening on http://0.0.0.0:3978
```

Then open Bot Framework Emulator v4.15.1, click **Open Bot**, set Bot URL to `http://localhost:3978/api/messages`, leave App ID / Password blank, and connect.

### Demo all three trust levels

By default every new Emulator user is `untrusted`. The Emulator generates a new user ID each session — find yours in the server logs first:

```
Received activity type='message' from='<id>' text='...'
```

Then pass it via `--user-id` to set the trust level before sending each message:

```bash
# Show current pairing state (no --user-id needed)
uv run python glc/channels/catalogue/teams/setup/trust_setup.py --show

# Pair as owner — next message → trust=owner_paired
uv run python glc/channels/catalogue/teams/setup/trust_setup.py --owner --user-id <id>

# Pair as regular user — next message → trust=user_paired
uv run python glc/channels/catalogue/teams/setup/trust_setup.py --user --user-id <id>

# Revoke — next message → trust=untrusted
uv run python glc/channels/catalogue/teams/setup/trust_setup.py --revoke --user-id <id>
```

### What the server logs show

```
2026-06-26 15:10:27 INFO Received activity type='message' from='4b7e88...' text='hello'
2026-06-26 15:10:27 INFO Parsed message: text='hello' trust='owner_paired' user='4b7e88...'
2026-06-26 15:10:27 INFO Returning inline reply: "GLC teams adapter received: 'hello' (trust=owner_paired)"
```

Each step maps directly to the adapter's logic: activity type guard → trust classification → allowlist check → ChannelMessage → reply.

> **Anonymous mode note:** the Emulator's anonymous mode bypasses Azure AD entirely. For the real authenticated send path you need `TEAMS_APP_ID`, `TEAMS_APP_PASSWORD`, and `TEAMS_TENANT_ID` as env vars and an actual Azure Bot registration. The demo works fully without these.
