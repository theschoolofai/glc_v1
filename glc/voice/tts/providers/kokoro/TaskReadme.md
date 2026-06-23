# Kokoro TTS — Task Readme (Group Kokoro)

Working task list for the **`kokoro`** slot (TTS, default path, difficulty:
medium). Source of truth is [`docs/ADAPTER_GUIDE.md`](../../../../../docs/ADAPTER_GUIDE.md)
and [`docs/VOICE_GUIDE.md`](../../../../../docs/VOICE_GUIDE.md) — if anything
here contradicts the guide, the guide wins.

## Status — branch `kokoro_adapter_imp`

`adapter.py` is **implemented** (commit `6ecf728`) and verified locally:

- ✅ **7/7 tests pass** — `uv run pytest tests/voice/tts/test_kokoro.py -v`
- ✅ **ruff clean** on the owned path
- ✅ **mypy clean** on the owned path
- ⏳ **Remaining:** real-model smoke (`uv pip install kokoro`), demo video,
  and the three submission steps (claim PR / implementation PR / artifacts).

Code-rubric points (1200 + 400 tests, 200 lint) are in hand on the mock path;
what's left is proving the **real** wire path for the demo and submitting.

## Identity & markers

| Field          | Value                                            |
|----------------|--------------------------------------------------|
| Slot           | `kokoro`                                          |
| Kind           | TTS, `prefer=default` (the daily-driver TTS path) |
| Group marker   | `# Group: group-kokoro`                           |
| Slot marker    | `# Slot: kokoro`                                  |
| Owned path     | `glc/voice/tts/providers/kokoro/`                 |

Both markers go on **their own line** in the PR body (not the title),
case-insensitive, leading whitespace allowed, **no trailing text on the line**
(trailing text breaks the CI match).

## Scope (what the boundary CI lets you touch)

Your only writable path is `glc/voice/tts/providers/kokoro/`. The boundary
check (`scripts/check_pr_boundaries.py`) rejects a PR whose diff strays outside
it — the only extra allowances are `GROUPS.md` and the PR template. A
shared-code change needs a separate PR under `@theschoolofai` review.

## Already done vs. what you build

- `runner.py` — **already written.** Lazy `_load()` caches the pipeline in a
  module global `_pipeline`; `synthesize()` returns `(wav_bytes, 24000)`.
  Extend only if you need extra knobs.
- `adapter.py` — **stub that raises `NotImplementedError`.** This is the one
  file you must implement.
- `schemas.py` — essentially empty. Leave it unless you add types.
- `README.md` — provider notes; update the Quirks section as you learn.

## The contract the tests enforce

Tests inject a fake via `Provider(config={"mock": mock})`. The house
convention ([`ADAPTER_GUIDE.md` §"The config dict"](../../../../../docs/ADAPTER_GUIDE.md))
is:

```python
mock = self.config.get("mock")
if mock is not None:
    return await mock.synthesize(text, voice_id)   # test path
# else: real Kokoro path via runner
```

The mock returns a fully-formed `SynthesizeResult`, so **delegating to it is
what makes all 7 tests pass**. The real branch is what the demo video must
exercise — passing CI does **not** prove the real call works.

## Tasks

### Phase 0 — Setup
- [x] Confirm markers: `# Group: group-kokoro` / `# Slot: kokoro`, each on its
      own line, no trailing text.
- [ ] Team lead forks `theschoolofai/glc_v1`; save the fork URL on the LMS page
      and in the team Repo URL field.
- [x] Read [`docs/ADAPTER_GUIDE.md` §9](../../../../../docs/ADAPTER_GUIDE.md)
      and [`docs/VOICE_GUIDE.md`](../../../../../docs/VOICE_GUIDE.md).
- [x] Baseline the tests:
      `uv run pytest tests/voice/tts/test_kokoro.py -v`.

### Phase 1 — Implement `adapter.py` (1200 + 400 pts) — ✅ done (commit `6ecf728`)
- [x] **Mock-delegate branch.** Reads `self.config.get("mock")`; if present,
      `return await mock.synthesize(text, voice_id)`. Satisfies all 7 tests.
      ([adapter.py:47-49](adapter.py#L47))
- [x] **Real Kokoro branch.** Calls `runner.synthesize(text, voice_id or "af_bella")`
      → `(wav_bytes, sample_rate)`, base64-encodes, returns
      `SynthesizeResult(..., mime="audio/wav", provider="kokoro", cost_usd=0.0)`.
      ([adapter.py:54-64](adapter.py#L54))
- [x] **Errors propagate.** No `try/except` around the mock call — `TTSError`
      bubbles with its `.status` intact (test 5).
- [x] **Sample rate not hardcoded.** Returned from the upstream/mock (test 4).
- [x] **No empty-text special case** — `""` returns a `SynthesizeResult`
      (test 6).
- [x] **Pipeline reuse.** Delegates to `runner.synthesize` (module-global
      `_pipeline`); no `KPipeline` per call (test 7).

Test-by-test (`tests/voice/tts/test_kokoro.py`):

| # | Test                          | What your code must do                                              |
|---|-------------------------------|--------------------------------------------------------------------|
| 1 | `name_matches`                | keep `name = "kokoro"` (already set)                               |
| 2 | `returns_synthesize_result`   | return `SynthesizeResult`, `provider=="kokoro"`, non-empty `audio_b64`, `sample_rate>0` |
| 3 | `passes_text_to_upstream`     | call `mock.synthesize(text, …)` → `received_calls[-1]["text_len"]==len(text)` |
| 4 | `records_sample_rate`         | propagate returned `sample_rate` (no hardcode)                    |
| 5 | `propagates_upstream_error`   | let `TTSError(status=502)` bubble up                              |
| 6 | `handles_empty_text`          | `""` → valid `SynthesizeResult`                                    |
| 7 | `pipeline_reuse`              | delegate to same mock / cached pipeline → `pipeline_load_count==1` |

### Phase 2 — Quality gates (200 pts) — ✅ passing
- [x] `uv run ruff check glc/voice/tts/providers/kokoro` — *All checks passed!*
- [x] `uv run mypy glc/voice/tts/providers/kokoro` — *Success: no issues found.*
      Required `audio_b64` / `mime` fields are set explicitly.
- [x] Adapter discipline (100 pts): no `langchain` / `crewai` / `autogen`
      imports. Trust-level classification is **not** required for voice slots.

### Phase 3 — Real-path proof & docs
- [ ] `uv pip install kokoro`; synthesize a real clip end-to-end (e.g. via
      `/v1/speak?prefer=default`) and confirm 24 kHz mono WAV out. **Not yet
      run** — this is the gap the demo must close.
- [x] README documents architecture, data flow, quirks, trust posture, and the
      test-to-code map (commit `6ecf728`). Re-confirm the Quirks section after
      the real-model smoke in case anything surprises you.

### Phase 4 — Submission (IST deadlines)
- [ ] **Claim PR** — due **Tue 2026-06-23 23:59**: one PR editing `GROUPS.md`
      for your row, title `claim: kokoro for group-kokoro`, `?template=claim.md`.
- [ ] **Implementation PR** — due **Wed 2026-07-01 23:59**: adapter PR with both
      markers + members list + demo link + quirks paragraph; confirm boundary CI
      passes (PR-template completeness = 100 pts).
- [ ] **Demo video** — due **Thu 2026-07-02 23:59**: YouTube/Loom/Vimeo link in
      the PR body showing a **real upstream Kokoro synthesis** (not the mock).
- [ ] Save all three artifacts (Fork URL, Implementation PR URL, Demo URL) on
      the LMS page.

## Rubric (2000 pts, scaled ÷10 ×200 by the grader)

| Item                                                   | Points |
|--------------------------------------------------------|--------|
| 6 structural tests pass (200 each)                     | 1200   |
| 1 behavioural test (`pipeline_reuse`)                  | 400    |
| ruff clean on owned path                               | 100    |
| mypy clean on owned path                               | 100    |
| PR template completeness (group/slot/members/demo/quirks) | 100 |
| Adapter discipline (no LangChain/CrewAI/AutoGen)       | 100    |
| **Total**                                              | **2000** |

## Watch out

The `pipeline_reuse` test only checks reuse **through the mock's counter** — a
pure mock-delegate adapter passes CI even if the real path re-loads the model
every call. The real `runner._load()` caching is what the demo (and real usage)
depends on, and it's where the behavioural points actually live: passing all 7
tests does not prove the real wire path works.
