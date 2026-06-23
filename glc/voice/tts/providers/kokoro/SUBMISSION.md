# Kokoro TTS — Submission Document (Group Kokoro / G9)

Everything required to submit the `kokoro` slot, and a ready-to-paste PR body.
Source of truth is the repo (`docs/ADAPTER_GUIDE.md`, the PR template, the
scorecard script). Where the assignment PDF disagrees with the repo, **the repo
wins** — two such conflicts are called out below.

---

## 1. What documentation is required

| Artifact | Where it lives | Scored? | Status |
|----------|----------------|---------|--------|
| Adapter `README.md` | `glc/voice/tts/providers/kokoro/README.md` | Indirectly (reviewer baseline) | ✅ done |
| **PR body** with the two markers + members + demo + quirks | Implementation PR description | ✅ **100 pts** (PR-template completeness) | ⏳ paste §4 |
| **Demo video** (real upstream, not the mock) | Link inside the PR body | ✅ part of the 400 behavioural pts | ⏳ record |
| In-code docstrings | `adapter.py`, `runner.py` | No (quality signal only) | ✅ done |
| `schemas.py` | owned path | No (may stay empty) | ✅ n/a |

The scorecard bot (`scripts/scorecard.py`) auto-checks the PR body for **four**
things and gives `0.5 × (1 − missing/4)` of the template score:

1. a `# Group: <name>` marker line,
2. a demo link matching `youtube.com | youtu.be | loom.com | vimeo.com`,
3. the word **`quirks`** or **`wire`** somewhere in the body,
4. the word **`members`** somewhere in the body.

Miss any one and you lose a quarter of that score — the PR body below contains
all four by construction.

---

## 2. Two conflicts with the assignment PDF (read before you submit)

**Group marker — use `Kokoro`, not `group-kokoro`.**
The PDF says `# Group: group-kokoro`. That string **fails the boundary check**
(`group 'group-kokoro' has no claimed slot in GROUPS.md`) because the check
normalizes against the `GROUPS.md` row `Group Kokoro` by stripping a leading
`"Group "` (a space, not a hyphen). Verified:

```
--group "group-kokoro"  -> [boundary] FAIL
--group "Kokoro"        -> [boundary] OK
--group "Group Kokoro"  -> [boundary] OK, but scorecard can't parse the space
```

➡ **Use `# Group: Kokoro`.** It's the only form that passes *both* the boundary
check and the scorecard regex.

**Claim PR — likely not required.**
The PDF lists a "Claim PR (due 2026-06-23)". But `GROUPS.md` now states *"Group
assignments are **fixed by the instructors** — there is no claim PR."* The repo
was migrated `CLAIMS.md → GROUPS.md` with fixed assignments. ➡ **Confirm with
the TA in the G9 sub-channel**, but per the current repo there is no claim PR to
open — only the implementation PR.

---

## 3. Pre-submission verification (run all, paste results into the PR)

```sh
# 1. Tests — must be 7 passed
uv run pytest tests/voice/tts/test_kokoro.py -v

# 2. Lint — must be clean on the owned path
uv run ruff check glc/voice/tts/providers/kokoro
uv run mypy  glc/voice/tts/providers/kokoro

# 3. Boundary — must say OK for group "Kokoro"
uv run python scripts/check_pr_boundaries.py --base origin/main --head HEAD --group "Kokoro"

# 4. Real path (for the demo) — proves the wire path, not just the mock
uv pip install kokoro
# then drive /v1/speak?prefer=default and capture audio out
```

Current state on branch `kokoro_adapter_imp`: tests **7/7 pass**, ruff **clean**,
mypy **clean**. The real-path smoke (step 4) is the one still open — it's what
the demo video exists to prove.

---

## 4. Ready-to-paste PR body

> Replace the three `<…>` placeholders (members, demo URL, anything in the
> reviewer notes). Keep the two `#` marker lines exactly as written — on their
> own line, no trailing text.

```markdown
# Implementation PR

# Group: Kokoro
# Slot: kokoro

## Group

- **Members**: <name @handle>, <name @handle>, <name @handle>

## What this PR adds

For a voice provider slot:

- [x] `glc/voice/tts/providers/kokoro/adapter.py` — `synthesize(text, voice_id)`
- [x] `glc/voice/tts/providers/kokoro/schemas.py` — no provider-specific types needed
- [x] All 7 tests at `tests/voice/tts/test_kokoro.py` pass

Implementation: one `synthesize` method with two branches. When the gateway or
test suite injects `config["mock"]`, every call is delegated to it (offline,
deterministic CI). With no mock, synthesis goes through `runner.synthesize`,
which lazy-loads the Kokoro `KPipeline` once into a module-global and reuses it,
then base64-encodes the 24 kHz mono WAV into a `SynthesizeResult(provider="kokoro")`.

## Demo

<YOUTUBE_OR_LOOM_OR_VIMEO_URL> — shows `/v1/speak?prefer=default` rendering real
Kokoro audio end to end (not the mock): text in, audible WAV out, with the
pipeline loading once and the second call reusing it.

## Wire-format quirks you hit

`KPipeline(lang_code="a")` downloads weights to `~/.cache/huggingface/` on the
first call, so the pipeline **must** be cached — we keep it in a module-global
in `runner.py` and import `runner` lazily so gateway boot doesn't pay the cost
on installs that never use TTS. The pipeline yields float32 samples at 24 kHz
mono; we pack them into a 16-bit PCM WAV and base64-encode for transport
(`mime="audio/wav"`). Voice ids are short strings (`af_bella`, `af_sky`,
`am_adam`); we default to `af_bella`. Cost is always `0.0` — Kokoro is local,
no paid API.

## Tests-included checklist

- [x] All 7 tests in `tests/voice/tts/test_kokoro.py` pass locally
- [x] `ruff check glc/voice/tts/providers/kokoro` is clean
- [x] `mypy glc/voice/tts/providers/kokoro` is clean
- [x] Adapter does **not** hold long-lived credentials in code or env files
- [ ] For channel slots: trust-level classification — N/A (TTS is outbound, not a channel)
- [ ] For channel slots: `allowed_senders` — N/A (outbound provider)
- [x] No imports from LangChain, CrewAI, AutoGen, or Open Interpreter

## Notes for the reviewer

TTS is an outbound provider, so it does not classify sender trust — that
contract belongs to channel adapters; `policy.yaml` still gates whether a
`speak` action is allowed before the router is reached. All 7 CI tests run
through the injected mock (offline); the real `runner.synthesize` path is
proven by the demo video linked above. <ANYTHING_ELSE>
```

---

## 5. Demo video — shot list (this is where the 400 behavioural pts live)

Passing CI does **not** prove the real call works. The video must show the real
wire path. Keep it ~1–2 minutes:

1. **Setup** — show `uv pip install kokoro` already done; no API key set (prove
   it's local/free).
2. **Real synthesis** — call `/v1/speak?prefer=default` (or `runner.synthesize`
   directly) with a sentence; play the resulting audio so it's audibly Kokoro.
3. **Pipeline reuse** — make a second call and show it's fast / no re-download,
   demonstrating the cached pipeline (the behavioural contract).
4. **Envelope** — show the `SynthesizeResult` (provider `kokoro`, `mime
   audio/wav`, `sample_rate 24000`, `cost_usd 0.0`).

Upload to YouTube/Loom/Vimeo and paste the URL into the PR `## Demo` section.

---

## 6. Submission checklist (LMS + GitHub)

- [ ] Confirm with TA whether a claim PR is needed (repo says no — see §2).
- [ ] Branch `kokoro_adapter_imp` pushed to the team fork.
- [ ] Implementation PR opened with the §4 body; boundary + scorecard CI green.
- [ ] Demo video recorded (§5) and linked in the PR.
- [ ] LMS page: Fork URL, Implementation PR URL, Demo URL all saved.
- [ ] Deadlines (IST): Implementation PR **2026-07-01 23:59**, demo link in PR
      **2026-07-02 23:59**, review window **2026-07-03 – 07-05**.
```
