# LINE Adapter End-to-End Harness

`harness.py` is a deterministic, scripted driver for the `line` channel adapter.
It replaces the manual "type a message on your phone through an HTTPS tunnel"
step from `RESTART_RUNBOOK.md` with a one-command run that pushes synthetic LINE
webhooks through the **real** relay and asserts the outcome.

It is test/demo wiring, not part of the graded adapter contract. It adds no new
behaviour: it reuses `live_bridge.create_app`, `RealLineTransport`, and
`line_signature`, and drives the same `Adapter` class that
`tests/channels/test_line.py` exercises. A green harness run is therefore real
evidence about the shipped `adapter.py`, not about a parallel reimplementation.

## Why it exists

The adapter could previously be exercised three ways, none of which is both
end-to-end and repeatable:

| Existing tool | Layer | Real LINE? | Deterministic? |
| --- | --- | --- | --- |
| `tests/channels/test_line.py` | adapter only, via `LineMock` | no | yes |
| `smoke_bridge.py` | bridge relay, `FakeLineTransport` | no | yes |
| 4-terminal live stack + phone | full relay | yes | no (manual) |

The harness fills the gap: the **full relay** (signature verify → adapter →
trust check → ack/agent/answer → outbound), driven by a script, with the EAG3-09
agent swapped for a canned stub so the bot's behaviour is reproducible.

## What it drives

```text
synthetic signed webhook
  -> live_bridge /callback (HMAC verify with the channel secret)
  -> Adapter.on_message()  (parse, stash reply token, classify trust)
  -> trust gate            (untrusted -> not-paired reply; owner -> continue)
  -> canned agent stub     (deterministic answer, no LLM gateway needed)
  -> Adapter.send() ack    (reply token if present, else push)
  -> Adapter.send() answer (push)
```

Because the agent is canned and the relay never touches the LLM gateway, the
harness runs standalone — no `:8109` gateway, no `:8200` agent, no tunnel.

## Modes

### capture (default, offline, no credentials)

Outbound is recorded by an in-process `CapturingTransport` and asserted. Nothing
hits the network. This proves the LINE-specific contract deterministically:
reply-token-then-push, `429` propagation, and disconnect handling.

### live (`--live`, needs `.env`)

Outbound goes to the real `api.line.me`. The default live run is the scripted
`conversation` scenario, which delivers a real ack + answer for each question to
the owner's LINE app; `--scenario owner` sends just the single two-message check.
For a cleaner chat with **one bubble per question** (answers only, no acks), run
`--scenario answers_only` — it drives the adapter directly and pushes just the
answers.

> **The one seam:** a synthetic webhook cannot carry a *valid* LINE reply token —
> those only exist inside a genuine webhook from LINE's servers, and the real
> `/reply` endpoint rejects anything else. So live mode **omits** the reply
> token, and both the ack and the answer are delivered via **push**. The
> reply-then-push *decision* is proven instead in capture mode, where a fake
> token is harmless because nothing is sent over the wire.

## Quickstart

```bash
# offline capture — runs every scenario, asserts, exits non-zero on any failure
uv run python -m glc.channels.catalogue.line.dev.harness

# real push to the owner's phone — sends the scripted conversation (needs .env)
uv run python -m glc.channels.catalogue.line.dev.harness --live

# run a single scenario in the current mode
uv run python -m glc.channels.catalogue.line.dev.harness --scenario conversation
uv run python -m glc.channels.catalogue.line.dev.harness --live --scenario owner
```

## Scenarios

| Scenario | Modes | What it proves |
| --- | --- | --- |
| `owner` | capture, live | paired owner → `owner_paired`; capture: 1st outbound consumes the reply token (`/reply`), 2nd falls back to push (`to`, no `replyToken`); live: ack + answer both delivered via push with status `200` |
| `conversation` | capture, live | pushes a scripted multi-question demo (`DEMO_CONVERSATION`); each question delivers an ack + answer, so live mode sends `2 × N` real messages. Edit `_CANNED_ANSWERS` to change the script |
| `answers_only` | capture, live | same demo script, but **one outbound per question** (answer only, no ack) — drives the `Adapter` directly to skip the bridge's ack step; live mode sends `N` messages |
| `stranger` | capture, live | unknown sender → `untrusted` → one not-paired reply, agent **not** called |
| `rate_limit` | capture | transport returns `{"status": 429}`; the relay propagates it and stops before the agent |
| `disconnect` | capture | `force_disconnect()` does not make `on_message` raise; the relay completes |
| `public_stranger` | capture | `config={"is_public_channel": True}` stranger is dropped or returned `untrusted` (driven against the `Adapter` directly, since the bridge does not set this flag) |

Default run sets:

- capture: `owner`, `conversation`, `answers_only`, `stranger`, `rate_limit`,
  `disconnect`, `public_stranger`
- live: `conversation` (its first question is the owner Dune one) — only the
  real owner id can actually receive a push; the other ids are sentinels LINE
  would reject. Run any other scenario in live mode explicitly with `--scenario`.

Capture-only scenarios print `SKIP` (not `FAIL`) when selected in live mode.

## Output and exit code

Each run prints a per-scenario `PASS` / `FAIL` / `SKIP` table and a summary
line. The process exits `0` only if no scenario failed, so the harness is safe
to gate CI or a pre-demo check on. Example (capture mode):

```text
LINE adapter end-to-end harness  —  mode=capture  owner=Uowner_harness
------------------------------------------------------------------------------
  [PASS] owner            trust=owner_paired, agent_called, 2 outbound payloads, ...
  [PASS] conversation     q1 delivered, q2 delivered, q3 delivered, q4 delivered, q5 delivered
  [PASS] answers_only     q1 answer, q2 answer, q3 answer, q4 answer, q5 answer
  [PASS] stranger         trust=untrusted, not_paired, agent not called
  [PASS] rate_limit       ack_status=429, rate_limited flag, agent not called
  [PASS] disconnect       relay completed, trust=owner_paired
  [PASS] public_stranger  trust_level=untrusted
------------------------------------------------------------------------------
  7 passed, 0 failed, 0 skipped
```

## How it works

- **Signed webhooks.** Each scenario builds a LINE webhook dict and signs the
  exact request bytes with `live_bridge.line_signature(raw, secret)`, posting
  `content=raw` (not `json=`) so the bytes the bridge re-hashes match what was
  signed. In capture mode the secret is a fixed local constant; in live mode it
  is the real `LINE_CHANNEL_SECRET`.
- **In-process bridge.** The webhook is delivered through
  `httpx.ASGITransport`, so the full FastAPI relay (including signature
  verification) runs without binding a port or starting uvicorn.
- **Transport injection.** `create_app(..., transport=, ask_agent=)` takes a
  `CapturingTransport` (capture) or a `RealLineTransport` (live) plus the canned
  `stub_agent`. The adapter under test is unchanged in both cases.
- **Isolated trust store.** The harness points `GLC_PAIRING_DB` at a throwaway
  temp file and resets the pairing-store singleton, so it never reads or writes
  the real `~/.glc/pairings.sqlite`. It seeds the owner with
  `get_pairing_store().force_pair_owner("line", owner_id)` — the same path the
  `pair_owner` fixture in the test suite uses — and leaves the stranger id
  unpaired so it classifies as `untrusted`.

## Live mode prerequisites

Put these in an untracked repo-root `.env` (already covered by `.gitignore`):

- `LINE_CHANNEL_ACCESS_TOKEN` — used to push to `api.line.me`
- `LINE_CHANNEL_SECRET` — used to sign and verify the synthetic webhook
- `LINE_OWNER_USER_ID` — your **real** LINE user id, so the push reaches your
  account (not the `Uowner_harness` sentinel used in capture mode)

The harness never prints the token or secret. Before a live run it is worth
confirming the access token is valid with a read-only probe that sends nothing:

```bash
# 200 + the bot's displayName/userId means the token is live
curl -s -H "Authorization: Bearer $LINE_CHANNEL_ACCESS_TOKEN" \
  https://api.line.me/v2/bot/info
```

Then deliver a real ack + answer to your phone:

```bash
uv run python -m glc.channels.catalogue.line.dev.harness --live --scenario owner
```

## Non-goals

- It does not edit or re-implement `adapter.py` / `schemas.py`; it is pure
  driver code.
- It does not assert LLM answer text (the agent is canned) or real-LINE response
  bodies byte-for-byte — only the trust classification, the chosen endpoint
  (reply vs push), and the delivery status.
- Live mode cannot exercise the real `/reply` endpoint (see the seam above);
  that contract is covered deterministically in capture mode.
```
