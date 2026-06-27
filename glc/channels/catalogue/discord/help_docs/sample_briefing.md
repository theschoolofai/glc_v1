---

# GLC v1 — ElevenLabs TTS Team Analysis

---

## 1. Project Understanding

### Overall Architecture

GLC v1 is a **Gateway for LLMs and Channels** running on port 8111. It has two major layers:

**Layer 1 — LLM Gateway (inherited from V9):**  
`/v1/chat`, `/v1/vision`, `/v1/embed`, `/v1/cost`, `/v1/providers` — unchanged from Session 9. Fully implemented.

**Layer 2 — Channel + Voice layer (new in S11):**
- `POST /v1/speak` → TTS dispatcher → one of five providers
- `POST /v1/transcribe` → STT dispatcher → one of three providers
- `WS /v1/channels/{name}` → channel adapter control plane
- `/v1/control/*` → out-of-band kill switch, pairing

**Security layers running across both:**
- Policy engine (`glc/policy/`) evaluates every tool call — runs outside the LLM context
- Trust-level classifier (`glc/security/trust_level.py`) classifies every inbound message
- Audit log (`glc/audit/`) — append-only, per-row commits
- Pairing store — rotating 6-digit codes, TTL-enforced

### Module Interaction Map

```
HTTP Client
    │
    ▼
glc/routes/speak.py          ← POST /v1/speak
    │
    ▼
glc/voice/tts/router.py      ← prefer="quality" → "elevenlabs"
    │
    ▼
glc/voice/tts/providers/
    elevenlabs/adapter.py    ← YOUR TEAM'S WORK (currently a stub)
    │
    ├── glc/voice/tts/base.py        (TTSProvider ABC, SynthesizeResult, TTSError)
    └── ElevenLabs API upstream
```

### Where ElevenLabs Fits

The router (router.py) maps `prefer="quality"` → `"elevenlabs"`. When a client calls `POST /v1/speak` with `prefer=quality`, the router dynamically imports `glc.voice.tts.providers.elevenlabs.adapter`, instantiates `Provider()`, and calls `await provider.synthesize(text, voice_id)`. Your team's adapter.py is the **only missing link** in this chain.

---

## 2. TTS Scope — Exactly What Your Team Owns

Per `GROUPS.md`, your owned paths are:

```
glc/voice/tts/providers/elevenlabs/
glc/voice/tts/providers/elevenlabs/**
```

The boundary CI check (`scripts/check_pr_boundaries.py`) **rejects any PR that touches files outside these paths.** You cannot touch router.py, base.py, `routes/speak.py`, pyproject.toml, or any test file outside your owned paths.

---

## 3. Files Requiring Work

### Files Your Team Must Deliver

| File | Current State | What Needs Writing | Effort |
|---|---|---|---|
| `glc/voice/tts/providers/elevenlabs/adapter.py` | Stub — raises `NotImplementedError` | Full implementation of `synthesize()` | **High** |
| `glc/voice/tts/providers/elevenlabs/schemas.py` | Empty (2 lines) | Pydantic types for ElevenLabs request/response shapes | **Low** |
| `glc/voice/tts/providers/elevenlabs/__init__.py` | Docstring only | No change needed | — |
| `glc/voice/tts/providers/elevenlabs/README.md` | Written by maintainers | No change needed | — |

### Files Already Provided (Read-Only for Your Team)

| File | Purpose |
|---|---|
| `tests/voice/tts/test_elevenlabs.py` | 7 tests you must pass — **do not modify** |
| `tests/voice/tts/mocks/elevenlabs_mock.py` | Mock API fake — **do not modify** |
| `glc/voice/tts/base.py` | `TTSProvider` ABC, `SynthesizeResult`, `TTSError` — your imports |
| `glc/voice/tts/router.py` | Dispatcher — wires `prefer=quality` to your adapter |
| `glc/routes/speak.py` | HTTP route — calls the router |

### What adapter.py Must Do (Derived from Tests + README)

| Requirement | Source |
|---|---|
| `Provider.name == "elevenlabs"` | `test_provider_name_matches` |
| Returns a valid `SynthesizeResult` with `provider="elevenlabs"`, non-empty `audio_b64`, `sample_rate > 0` | `test_synthesize_returns_synthesize_result` |
| Passes `text` through to the upstream call (length must match) | `test_synthesize_passes_text_to_upstream` |
| Respects `canned_sample_rate` from mock | `test_synthesize_records_sample_rate` |
| Propagates upstream errors as `TTSError` with correct HTTP status | `test_synthesize_propagates_upstream_error` |
| Handles empty text gracefully (returns a result, doesn't crash) | `test_synthesize_handles_empty_text` |
| Tracks monthly char usage; raises `TTSError(status=429)` with "quota" or "limit" in message **before** sending when quota would be exceeded | `test_channel_specific_behaviour_free_tier_quota_tracking` |
| When `config["mock"]` is present, call `mock.synthesize()` instead of hitting the real API | `ElevenlabsMock` usage pattern (same as `system_fallback` uses config) |
| Real path: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}` | README |
| Real auth: `xi-api-key: <KEY>` header (not Bearer) | README |
| Real body: `{"text": "...", "model_id": "eleven_flash_v2_5"}` | README |
| Default voice_id: `21m00Tcm4TlvDq8ikWAM` (Rachel) | README |
| Chunk text at ≤5000 chars/request on the free tier | README |

---

## 4. Dependency Analysis

```
[PHASE 0 — Research, parallel]
  M2: Study mock + tests → behavioural contract document
  M3: Study ElevenLabs API docs → API contract document
  M9: Study ruff/mypy config in pyproject.toml → style rules

[PHASE 1 — Foundation, parallel after PHASE 0]
  M4: Class skeleton + config injection + mock path
        depends on: M2 (mock contract)
  M8: schemas.py Pydantic types
        depends on: M3 (API shapes)

[PHASE 2 — Core, sequential on M4's work]
  M5: HTTP call + response parsing
        depends on: M4 (skeleton), M3 (API contract), M8 (schemas)
  M6: Text chunking (≤5000 chars) + multi-chunk audio merge
        depends on: M4 (skeleton)

[PHASE 3 — Robustness, parallel after M5]
  M7: Quota tracking + pre-flight 429 check
        depends on: M5 (HTTP call in place)
  M10: Error handling + upstream error propagation
        depends on: M5 (HTTP call in place)

[PHASE 4 — Quality, parallel]
  M9: Type annotations + ruff + mypy compliance
        depends on: M5, M6, M7, M10 (code mostly done)
  M11: Live API integration test + env setup validation
        depends on: M5 (basic HTTP path working)

[PHASE 5 — Integration]
  M1 (Leader): Final review, all 7 tests pass, PR open
        depends on: all above
```

**Can work in parallel from day one:** M2, M3, M8, M9 (ruff study)  
**Must be sequential:** M4 → M5 → M7, M10  
**Critical path:** M2/M3 → M4 → M5 → M7 → tests pass → PR

---

## 5. Task Distribution (11 Members)

---

### Member 1 — Team Leader (You)

**Objective:** Interface design, integration, review, PR submission  
**Files:** All files under `glc/voice/tts/providers/elevenlabs/`  
**Deliverables:**
- Define the internal contract for how adapter.py components interact (quota store location, chunking strategy, mock delegation pattern)
- Review every member's work before it is merged into the team's feature branch
- Ensure all 7 tests pass on the combined branch
- Open the implementation PR with the required `# Group: Group ElevenLabs` and `# Slot: elevenlabs` markers in the PR description
- Coordinate with other groups if shared-code changes are needed (they won't be for your scope)

**Dependencies:** Unblocked from day one  
**Difficulty:** Medium  
**Effort:** ~4–6 hours spread across the sprint

---

### Member 2 — Test & Mock Analyst

**Objective:** Deeply understand the 7 tests and the mock, produce a behavioral specification  
**Files to read:** `tests/voice/tts/test_elevenlabs.py`, `tests/voice/tts/mocks/elevenlabs_mock.py`  
**Deliverables:**
- A written spec (can be a team-internal doc or comments in adapter.py) that maps each test to the exact adapter behavior it requires
- Specifically document: how `monthly_chars_used` and `monthly_chars_limit` are exposed by the mock, what `received_calls` records, how `upstream_failure` triggers, what `canned_sample_rate` does
- Hand this to M4 before M4 starts coding

**Dependencies:** None  
**Difficulty:** Easy  
**Effort:** 2–3 hours  
**Suggested order:** Day 1 immediately

---

### Member 3 — API Research

**Objective:** Document the real ElevenLabs Flash v2.5 API contract  
**Reference:** `https://elevenlabs.io/docs/api-reference/text-to-speech` (cited in the mock docstring)  
**Deliverables:**
- Document the exact HTTP request shape: endpoint URL pattern, headers, JSON body fields, response body shape (is it raw bytes? JSON wrapper? Content-Type?)
- Document rate limit error response shapes (what status code + body does ElevenLabs return when quota is exceeded?)
- Document the free tier quota enforcement behavior
- Clarify whether the response is raw MP3 bytes or JSON containing audio
- Hand this to M5 before M5 starts coding

**Dependencies:** None  
**Difficulty:** Easy  
**Effort:** 2–3 hours  
**Suggested order:** Day 1 immediately, parallel with M2

---

### Member 4 — Adapter Skeleton + Mock Path

**Objective:** Implement the class skeleton and mock delegation, making the first 2 tests pass  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py`  
**Deliverables:**
```python
class Provider(TTSProvider):
    name = "elevenlabs"

    def __init__(self, config=None):
        super().__init__(config)
        # read ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID from env
        # initialise quota state

    async def synthesize(self, text, voice_id=None):
        # delegate to mock if config["mock"] is set
        mock = self.config.get("mock")
        if mock is not None:
            return await mock.synthesize(text, voice_id)
        # else: call real API (M5 fills this in)
        raise NotImplementedError("real path TBD")
```
- `test_provider_name_matches` should pass after this
- `test_synthesize_returns_synthesize_result` should pass after M5 integrates

**Dependencies:** M2's spec  
**Difficulty:** Easy  
**Effort:** 2–3 hours  
**Suggested order:** Start after M2 delivers the spec (Day 1 afternoon or Day 2)

---

### Member 5 — HTTP Call + Response Parsing

**Objective:** Implement the real ElevenLabs API HTTP call using `httpx`  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py`  
**Deliverables:**
- `async with httpx.AsyncClient() as client:` POST to `https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`
- Set `xi-api-key` header from `ELEVENLABS_API_KEY`
- Set body `{"text": text, "model_id": "eleven_flash_v2_5"}`
- Decode the response (raw MP3 bytes) to base64
- Populate `SynthesizeResult` with `audio_b64`, `mime="audio/mpeg"`, `sample_rate=44100`, `provider="elevenlabs"`, `cost_usd=0.0`
- `test_synthesize_records_sample_rate` must pass

**Dependencies:** M4 skeleton, M3 API contract  
**Difficulty:** Medium  
**Effort:** 3–5 hours  
**Suggested order:** Day 2 after M4 delivers skeleton

---

### Member 6 — Text Chunking

**Objective:** Handle the free-tier limitation of ~5000 chars per request  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py`  
**Deliverables:**
- Function `_chunk_text(text: str, max_chars: int = 5000) -> list[str]` that splits on sentence boundaries (`.`, `?`, `!`) to avoid cutting mid-word
- In `synthesize()`, if `len(text) > 5000`, call the API once per chunk and concatenate raw audio bytes before base64-encoding
- Edge case: single word/token longer than 5000 chars should still be sent as one chunk (not split mid-word)
- Empty text must not crash (`test_synthesize_handles_empty_text`)
- Keep `text_len` recorded in `received_calls` as the total original length (not per-chunk)

**Dependencies:** M4 skeleton, M5 HTTP call  
**Difficulty:** Medium  
**Effort:** 3–4 hours  
**Suggested order:** Day 2–3, after M5 delivers HTTP call

---

### Member 7 — Quota Tracking

**Objective:** Implement the monthly character quota check — the 7th behavioural test  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py`  
**Deliverables:**
- Read `mock.monthly_chars_used` and `mock.monthly_chars_limit` from the mock when in mock mode (the mock exposes these as attributes)
- For the real path: maintain a persistent quota counter (e.g., stored in a simple state file under `~/.glc/elevenlabs_quota.json` with the month key)
- Before any HTTP call, check if `monthly_chars_used + len(text) > monthly_chars_limit`
- If over quota: raise `TTSError("monthly quota limit exceeded", status=429)` — message must contain "quota" or "limit"
- This check must happen **before** the HTTP request is sent
- `test_channel_specific_behaviour_free_tier_quota_tracking` must pass

**Dependencies:** M5 HTTP call structure, M2's spec on mock quota attributes  
**Difficulty:** Medium  
**Effort:** 3–4 hours  
**Suggested order:** Day 3, after M5

---

### Member 8 — Pydantic Schemas

**Objective:** Define ElevenLabs-specific Pydantic types in schemas.py  
**Files:** `glc/voice/tts/providers/elevenlabs/schemas.py`  
**Deliverables:**
- `ElevenLabsRequest(BaseModel)` with fields: `text: str`, `model_id: str = "eleven_flash_v2_5"`, `voice_settings: dict | None = None`
- `ElevenLabsVoiceSettings(BaseModel)` with `stability: float = 0.5`, `similarity_boost: float = 0.75` (ElevenLabs API parameters)
- Any other API-specific types M3 identifies from the API docs
- Import and use these in adapter.py so the HTTP body is constructed from the schema (not a raw dict)

**Dependencies:** M3's API contract documentation  
**Difficulty:** Easy  
**Effort:** 2–3 hours  
**Suggested order:** Day 2, parallel with M5

---

### Member 9 — Type Annotations + Lint Compliance

**Objective:** Ensure adapter.py and schemas.py pass `ruff` and `mypy` cleanly  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py`, `glc/voice/tts/providers/elevenlabs/schemas.py`  
**Deliverables:**
- Add `from __future__ import annotations` at top of all files
- Add full type annotations to all functions and methods
- Run `ruff check glc/voice/tts/providers/elevenlabs/` and fix all violations
- Run `mypy glc/voice/tts/providers/elevenlabs/` and resolve all errors (strict=False per pyproject.toml)
- Confirm `line-length = 110` and `target-version = py311` are respected
- No unused imports, no bare `except:`, no shadowing of builtins

**Dependencies:** M4, M5, M6, M7, M8 (code mostly complete)  
**Difficulty:** Easy  
**Effort:** 2–3 hours  
**Suggested order:** Day 3–4 (final pass before PR)

---

### Member 10 — Error Handling + Test Validation

**Objective:** Implement upstream error propagation and validate all 7 tests pass  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py`  
**Deliverables:**
- Ensure `httpx.HTTPStatusError` is caught and re-raised as `TTSError(message, status=response.status_code)`
- Ensure `httpx.RequestError` (network errors) is caught and re-raised as `TTSError(message, status=503)` or similar
- `test_synthesize_propagates_upstream_error` must pass (mock injects `upstream_failure = (502, "upstream broken")` — the adapter must re-raise as `TTSError` with `status=502`)
- Run `uv run pytest tests/voice/tts/test_elevenlabs.py -v` on the integrated branch and confirm all 7 tests are green
- Document any test failures and report to M1

**Dependencies:** M5 HTTP call, M7 quota tracking  
**Difficulty:** Medium  
**Effort:** 3–4 hours  
**Suggested order:** Day 3–4

---

### Member 11 — Live API Integration + Environment Setup

**Objective:** Validate the adapter against the real ElevenLabs API and write the setup guide  
**Files:** `glc/voice/tts/providers/elevenlabs/adapter.py` (read), new test marked `requires_live_api`  
**Deliverables:**
- Obtain a free ElevenLabs API key from `elevenlabs.io`
- Run the adapter against the real API manually and confirm audio is returned
- Write one additional test function `test_live_synthesize` in the `tests/voice/tts/` directory, marked `@pytest.mark.requires_live_api`, that calls the real endpoint without a mock
- Document in the team's internal notes: how to set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`, how to run local tests, what the free-tier limits are in practice

**Note:** This test must be marked `requires_live_api` so CI skips it — CI runs with `-m "not requires_live_api"`.

**Dependencies:** M5 HTTP call working  
**Difficulty:** Easy–Medium  
**Effort:** 3–4 hours  
**Suggested order:** Day 3, once M5 is done

---

## 6. Leader Responsibilities

| Responsibility | Detail |
|---|---|
| **Interface contract** | Decide: where is quota state stored in the real (non-mock) path? How are chunks merged? Define these before M4 starts coding. |
| **Branch strategy** | Create one team feature branch `feat/elevenlabs-tts`. Members work on sub-branches and PR into it. You merge into the team branch. |
| **PR description** | The PR must contain `# Group: Group ElevenLabs` and `# Slot: elevenlabs` exactly — CI boundary check reads these |
| **Review order** | Review M4 first (skeleton), then M8+M5 together, then M6+M7, then M9+M10 |
| **CI gate** | Confirm the adapter-pr.yml workflow passes: boundary check, test-changed-slot (7 tests), scorecard |
| **Scorecard** | The CI auto-comments a rubric scorecard — monitor it after the PR opens |
| **Merge** | `@theschoolofai` CODEOWNER review is required — you cannot self-merge; coordinate timing |

---

## 7. Suggested Timeline

```
Day 1:
  M1:  Define internal contract (quota store, chunking strategy, mock pattern)
  M2:  Analyze tests + mock → spec doc
  M3:  Analyze ElevenLabs API → API contract doc
  M9:  Review ruff/mypy config, note style rules

Day 2:
  M4:  Adapter skeleton + mock path (needs M2 spec)
  M8:  schemas.py (needs M3 API contract)
  M11: Get API key, test account setup

Day 3:
  M5:  HTTP call + response parsing (needs M4 + M3)
  M6:  Text chunking (needs M4, parallel to M5)

Day 4:
  M7:  Quota tracking (needs M5)
  M10: Error handling (needs M5)
  M11: Live API test (needs M5)

Day 5:
  M9:  Final ruff + mypy pass
  M10: Run all 7 tests, confirm green
  M1:  Final review, open PR

Day 6–7:
  M1:  Address review comments, resubmit, await CODEOWNER merge
```

---

## 8. Risks and Recommendations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Merge conflicts in adapter.py** | High — 6+ people touching one file | Use M1 as the integrator. Members submit their logic as functions or clearly delimited blocks on sub-branches. M1 merges sequentially: skeleton → HTTP → chunking → quota → errors. |
| **Boundary CI rejection** | Medium | Never touch anything outside `glc/voice/tts/providers/elevenlabs/`. Even fixing a typo in router.py will fail the boundary check. |
| **Mock vs. real path confusion** | Medium | The pattern is clear: `if config.get("mock"): delegate to mock`. Tests always inject a mock. M4 must establish this pattern first and document it clearly. |
| **Quota state location** | Medium | For the mock path, quota is on `mock.monthly_chars_used`. For the real path, you need persistent state. Recommendation: a simple JSON file under `~/.glc/`. M1 must decide this before M7 starts. |
| **ElevenLabs response format** | Medium | The README says "Default output is MP3 (44.1 kHz)". M3 must confirm whether the response body is raw bytes or a JSON wrapper containing base64. If it's raw bytes, `base64.b64encode(response.content).decode("ascii")` is the conversion. |
| **Empty text edge case** | Low | `test_synthesize_handles_empty_text` requires a valid `SynthesizeResult` for empty input. The adapter must short-circuit and return a result with empty or minimal audio rather than sending an empty string to the API. |
| **chunking + quota interaction** | Medium | When text is chunked, quota must be checked for `total len(text)`, not per-chunk. Otherwise the quota test could be gamed. M7 must coordinate with M6 on the check order. |
| **httpx not in main deps** | Low | `httpx>=0.27` is already in pyproject.toml — no pyproject.toml change needed. |
| **`ruff B` rules on async** | Low | `ruff` is configured with `select = ["E", "F", "I", "W", "UP", "B"]`. `B` rules include things like not using bare `except`. M9 must catch these. |
| **PR open too late** | Low | PR should be open by Day 5 to allow CODEOWNER review time before the 2026-07-05 deadline. |

### Recommended Development Order to Minimize Conflicts

1. **M1 decides** the quota store location and chunking merge strategy — commit this as code comments in adapter.py on Day 1
2. **M4 commits** the skeleton with `# TODO: HTTP path (M5)`, `# TODO: chunking (M6)`, `# TODO: quota (M7)` markers
3. **M5, M6** work on **separate functions** (`_do_synthesize_single()`, `_chunk_text()`), not inline in `synthesize()`
4. **M7** adds quota logic as a separate `_check_quota()` method
5. **M10** adds error handling as a separate `_call_upstream()` wrapper
6. **M1** integrates all functions into the final `synthesize()` method body
7. **M9** does the final type/lint pass on the integrated file
8. **M10** confirms all 7 tests pass on the final integrated file before PR is opened
