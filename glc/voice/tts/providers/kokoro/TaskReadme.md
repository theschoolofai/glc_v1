# Kokoro TTS — Task Readme (Group Kokoro)

Working task list for the **`kokoro`** slot (TTS, default path, difficulty:
medium). Source of truth is [`docs/ADAPTER_GUIDE.md`](../../../../../docs/ADAPTER_GUIDE.md)
and [`docs/VOICE_GUIDE.md`](../../../../../docs/VOICE_GUIDE.md) — if anything
here contradicts the guide, the guide wins.

## Status — branch `kokoro_adapter_imp`

`adapter.py` is **implemented and hardened** (latest commit `d501536`) and
verified locally:

- ✅ **11/11 tests pass** — `uv run pytest tests/voice/tts/test_kokoro.py -v`
  (the original 7 + 4 new real-path/error-handling tests).
- ✅ **ruff clean** on the owned path.
- ✅ **mypy clean** on the owned path (5 source files, incl. `demo.py`).
- ✅ **Real path verified** — `uv pip install kokoro` + `demo.py` produce real
  24 kHz mono WAV; **demo video recorded** (https://youtu.be/2_b4V3v654s).
- ✅ **Members list** filled in `README.md`.
- ⏳ **Remaining:** open the implementation PR and save the LMS artifacts.

All rubric-relevant code work is done and proven (mock *and* real paths). What's
left is the GitHub PR + LMS submission steps.

## Identity & markers

| Field          | Value                                            |
|----------------|--------------------------------------------------|
| Slot           | `kokoro`                                          |
| Kind           | TTS, `prefer=default` (the daily-driver TTS path) |
| Group marker   | `# Group: Kokoro`  ⚠️ **not** `group-kokoro`      |
| Slot marker    | `# Slot: kokoro`                                  |
| Owned path     | `glc/voice/tts/providers/kokoro/`                 |

Both markers go on **their own line** in the PR body (not the title),
case-insensitive, leading whitespace allowed, **no trailing text on the line**
(trailing text breaks the CI match).

> ⚠️ **Verified marker conflict.** The assignment PDF says `group-kokoro`, but
> that **fails the boundary check** (`group 'group-kokoro' has no claimed slot`).
> The check normalizes against the `GROUPS.md` row `Group Kokoro` by stripping a
> leading `"Group "` (space, not hyphen). `# Group: Kokoro` is the only form that
> passes **both** the boundary check and the scorecard regex. See `SUBMISSION.md`
> §2 for the proof.

## Scope (what the boundary CI lets you touch)

Your only writable path is `glc/voice/tts/providers/kokoro/`. The boundary
check (`scripts/check_pr_boundaries.py`) rejects a PR whose diff strays outside
it — the only extra allowances are `GROUPS.md` and the PR template. A
shared-code change needs a separate PR under `@theschoolofai` review.

## Files in the slot (current branch)

- `runner.py` — pre-written. Lazy `_load()` caches the pipeline in a module
  global `_pipeline`; `synthesize()` returns `(wav_bytes, 24000)`.
- `adapter.py` — ✅ **implemented + hardened.** `synthesize` defaults the voice,
  delegates to `config["mock"]` when injected, else offloads the real runner to
  a worker thread and maps failures to a structured `TTSError(502)`.
- `demo.py` — ✅ **added.** Drives the real path (no mock) to synthesize three
  showcase sentences and prove pipeline-reuse + voice switching for the video.
- `schemas.py` — empty; no provider-specific types needed.
- `README.md` — ✅ members, demo link, architecture, quirks, trust posture, and
  the test-to-code map.
- `SUBMISSION.md` — ✅ submission package + ready-to-paste PR body.

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

**Hardening added since the first cut** (commits `a9712fa`, `8d4a027`):

- [x] **Voice default at the top** — `voice = voice_id or DEFAULT_VOICE_ID`
      resolves once, before the mock/real split, so both branches see the same
      value ([adapter.py:48](adapter.py#L48)). Covered by new test 8.
- [x] **Real path off the event loop** — `await asyncio.to_thread(runner.synthesize, …)`
      so CPU-bound inference doesn't block the gateway ([adapter.py:67](adapter.py#L67)).
- [x] **Structured failures** — `TTSError` passes through; any other exception
      (missing `kokoro`/`numpy`, model error) is wrapped as `TTSError(status=502)`
      ([adapter.py:70-78](adapter.py#L70)). Covered by new tests 9 & 11.
- [x] **No malformed envelope** — empty `wav_bytes` raises `TTSError(502)` rather
      than emitting a 0-byte `audio/wav` ([adapter.py:80-84](adapter.py#L80)).
      Covered by new test 10.

Test-by-test (`tests/voice/tts/test_kokoro.py`) — **11 tests, 11 green**:

| # | Test                          | What your code does to pass it                                     |
|---|-------------------------------|--------------------------------------------------------------------|
| 1 | `provider_name_matches`       | `name = "kokoro"` (already set)                                    |
| 2 | `returns_synthesize_result`   | `SynthesizeResult`, `provider=="kokoro"`, non-empty `audio_b64`, `sample_rate>0` |
| 3 | `passes_text_to_upstream`     | `mock.synthesize(text, …)` → `received_calls[-1]["text_len"]==len(text)` |
| 4 | `records_sample_rate`         | propagate returned `sample_rate` (no hardcode)                    |
| 5 | `propagates_upstream_error`   | `TTSError(status=502)` bubbles up                                  |
| 6 | `handles_empty_text`          | `""` → valid `SynthesizeResult`                                    |
| 7 | `pipeline_reuse` *(behavioural)* | same mock / cached pipeline → `pipeline_load_count==1`         |
| 8 | `none_voice_id_resolved_to_default_before_mock` | `voice_id=None` reaches the mock as `af_bella` |
| 9 | `runner_generic_exception_wrapped_as_tts_error` | runner raising `RuntimeError` → `TTSError(502)` |
| 10 | `runner_empty_audio_raises_tts_error` | runner returning `b""` → `TTSError(502)`               |
| 11 | `runner_tts_error_passes_through_unchanged` | runner's own `TTSError` is not double-wrapped     |

> Tests 1–7 are the rubric tests (6 structural + 1 behavioural). Tests 8–11 are
> extra coverage we added for the hardening — they don't add rubric points but
> guard the real path the demo depends on.

### Phase 2 — Quality gates (200 pts) — ✅ passing
- [x] `uv run ruff check glc/voice/tts/providers/kokoro` — *All checks passed!*
- [x] `uv run mypy glc/voice/tts/providers/kokoro` — *Success: no issues found.*
      Required `audio_b64` / `mime` fields are set explicitly.
- [x] Adapter discipline (100 pts): no `langchain` / `crewai` / `autogen`
      imports. Trust-level classification is **not** required for voice slots.

### Phase 3 — Real-path proof & docs — ✅ done
- [x] `uv pip install kokoro`; `demo.py` synthesizes real clips end-to-end and
      confirms 24 kHz mono WAV out. **Verified locally.**
- [x] **Demo video recorded** — https://youtu.be/2_b4V3v654s (real path: load,
      reuse, voice switch). Linked in `README.md`.
- [x] README documents members, demo, architecture, quirks, trust posture, the
      real-path run instructions, and the test-to-code map.

### Phase 4 — Submission (IST deadlines)
- [ ] **Claim PR** — *likely not required.* `GROUPS.md` states assignments are
      **fixed by instructors, no claim PR** (overrides the PDF's 2026-06-23
      claim step). **Confirm with the TA in the G9 sub-channel**, then check off.
- [ ] **Implementation PR** — due **Wed 2026-07-01 23:59**: open from
      `kokoro_adapter_imp`, paste the PR body from `SUBMISSION.md` §4 (marker
      `# Group: Kokoro`, members, demo link, quirks). Confirm boundary CI + the
      scorecard comment are green (PR-template completeness = 100 pts).
- [x] **Demo video** — recorded; goes in the PR `## Demo` section
      (https://youtu.be/2_b4V3v654s).
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

- The `pipeline_reuse` test only checks reuse **through the mock's counter** —
  passing CI alone doesn't prove the real path reuses the pipeline. We close
  that gap with `demo.py` + the recorded video (https://youtu.be/2_b4V3v654s),
  which exercise `runner`'s module-global singleton for real.
- **Marker:** submit `# Group: Kokoro`, never `group-kokoro` (the PDF's form
  fails the boundary check — see Identity table and `SUBMISSION.md` §2).
- **Commits:** per repo `CLAUDE.md`, do **not** add a `Co-Authored-By` trailer,
  and never push to `main` — branch + PR only.
