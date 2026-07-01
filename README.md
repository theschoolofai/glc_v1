# GLC v1 — Gateway for LLMs and Channels

> **Session 12 update**: this is the S11 deliverable. S12's deliverable
> is **[theschoolofai/glc_v2](https://github.com/theschoolofai/glc_v2)** —
> a containerised, Modal-deployed version of this gateway, designed
> as the pen-test attack target for the S12 assignment. Read v2's
> README to see what changed and how to participate in the
> pen-testing assignment.

GLC v1 is the Session 11 deliverable. It absorbs the V9 LLM gateway
(text chat, vision, embeddings, cost ledger, provider routing) and
adds the new channel and voice layer for the first time. The S9 agent
runtime and the S10 Computer-Use skill point at this gateway unchanged.

Port: **8111** (V9 stays on 8109 for older student work).

## Install

```sh
cd glc_v1
uv sync
uv run glc serve
```

The first boot creates `~/.glc/` with the audit log, pairing store,
gateway db, channels.yaml, and a per-installation token. The token
gates `/v1/control/*` and the channel WebSocket. Print it with
`uv run glc token`.

## Point your existing S9 / S10 client at it

```sh
export LLM_GATEWAY_V9_URL=http://localhost:8111
```

Every V9 route — `/v1/chat`, `/v1/chat/batch`, `/v1/vision`, `/v1/embed`,
`/v1/cost/by_agent`, `/v1/providers`, `/v1/capabilities`, `/v1/status`,
`/v1/routers`, `/v1/calls`, `/v1/embedders` — works identically against
this port. The S9 Browser skill and S10 Computer-Use skill require no
code changes.

## New surfaces

| Route                            | Purpose                                         |
|----------------------------------|-------------------------------------------------|
| `POST /v1/transcribe`            | STT dispatcher → `groq_whisper` / `whisper_cpp` / `gemini_live`  |
| `POST /v1/speak`                 | TTS dispatcher → `kokoro` / `elevenlabs` / `cartesia` / `gemini_live` / `system_fallback` |
| `WS /v1/channels/{name}`         | Channel adapter control plane                   |
| `POST /v1/control/kill`          | Out-of-band kill switch (loopback only)         |
| `POST /v1/control/pair`          | Issue a rotating six-digit pairing code         |
| `POST /v1/control/pair/confirm`  | Owner confirms a pairing code                   |
| `GET /v1/control/presence`       | Channels registered, paired users, uptime       |

## Daemonise

```sh
./daemon/install.sh                # macOS launchd, Linux systemd, Windows NSSM
./daemon/install.sh --uninstall    # remove the service
./daemon/install.sh --models       # fetch Kokoro + whisper.cpp base model
```

## Your group's adapter

There are **22 group slots**:

- **15 channel adapters** under `glc/channels/catalogue/<name>/`.
- **7 voice providers** under `glc/voice/stt/providers/<name>/` and
  `glc/voice/tts/providers/<name>/` (3 STT + 4 TTS).
  `system_fallback` ships fully implemented and is **not** a slot.

Group → slot assignments are **fixed by the instructors** and listed in
[`GROUPS.md`](GROUPS.md). There is no claim PR — the assignment table
is the source of truth. If you think your group's row is wrong, raise
it in the S11 chat (`G<n>` sub-channel) and a TA will correct it.

Workflow:

1. Find your group's row in [`GROUPS.md`](GROUPS.md). Note the slot
   name and the `Owned paths`.
2. Read [`docs/ADAPTER_GUIDE.md`](docs/ADAPTER_GUIDE.md).
3. Implement `adapter.py` (and `schemas.py` if needed) against the
   mock-API fake under `tests/channels/mocks/` or
   `tests/voice/{stt,tts}/mocks/`.
4. Open your implementation PR. Include `# Group: <name>` and
   `# Slot: <slot>` markers in the PR description.
5. The [`adapter-pr.yml`](.github/workflows/adapter-pr.yml) workflow
   runs three jobs against your PR:
   - **boundary** — fails if your diff touches files outside your
     `Owned paths` in GROUPS.md.
   - **test-changed-slot** — runs only the matching
     `test_<slot>.py`, plus `ruff` and `mypy` on your slot's dir.
   - **scorecard** — auto-comments a per-group rubric scorecard.
6. Branch protection requires a CODEOWNER review. The
   [`@theschoolofai`](.github/CODEOWNERS) team merges on green.

## Pass CI

`.github/workflows/ci.yml` runs on every push and PR:

- `ruff check .` and `ruff format --check .`
- `mypy glc tests`
- `pytest tests/ --cov=glc --cov-fail-under=80 -m "not requires_live_api"`
- [`scripts/validate_envelope.py`](scripts/validate_envelope.py) —
  envelope must not be re-shaped per adapter
- [`scripts/validate_policy.py`](scripts/validate_policy.py) —
  `policy.yaml` must parse and the five lecture defaults must load
- [`scripts/validate_claims.py`](scripts/validate_claims.py) —
  no duplicate group rows in `GROUPS.md`

## Architecture and rationale

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The six architectural
moves from Session 11 §7 are the operational answer to the four
documented OpenClaw incidents: ClawJacked, Summer Yue email deletion,
Moltbook DB exposure, and the malicious-skills taxonomy.

## What this scaffold does NOT do

- It does not ship any working channel adapter. Every `adapter.py` in
  `glc/channels/catalogue/` raises `NotImplementedError`. That is the
  group assignment.
- It does not hold paid-API defaults. Free-tier sign-ups are linked
  in [`docs/VOICE_GUIDE.md`](docs/VOICE_GUIDE.md).
- It does not pull LangChain, CrewAI, AutoGen, or Open Interpreter.

## License

MIT — see [`LICENSE`](LICENSE).
