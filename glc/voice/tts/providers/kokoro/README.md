# Kokoro-82M — TTS provider (`prefer="default"`)

**Group:** G9 — Group Kokoro · **Slot:** `kokoro` (TTS) · **Owned path:**
`glc/voice/tts/providers/kokoro/`

## Group members

| Name | GitHub |
|------|--------|
| Abhijeet Upadhyay | |
| Amritanshu Singh | |
| Dheeraj Hegde | @Dheeraj-Hegde |
| Gaurav Pandey | |
| Prateek Mohan Garg | @pmgarg |
| Satya Nayak | |
| Soubhik Maji | @majisoubhik01 |
| Sri Varshini Dharmaraj | @srijadharmaraj1|
| Sujit Kumar Thakur | @sujthr |
| Vikas Gupta | @guptavik |
| Yashwanth G | @gyashwanth2711|

## Demo

[![Kokoro TTS demo](https://img.youtube.com/vi/2_b4V3v654s/0.jpg)](https://youtu.be/2_b4V3v654s)

[https://youtu.be/2_b4V3v654s](https://youtu.be/2_b4V3v654s)

The default voice path for GLC v1. Kokoro-82M is an open-weights
text-to-speech model: 82M parameters, runs faster than realtime on a
laptop CPU, no API key, no network egress, zero per-call cost. That is
the local-first, free-by-default posture GLC wants for the voice the
agent uses most (Session 11 §7).

## Architecture

`/v1/speak?prefer=default` → `glc/voice/tts/router.py` maps `default` →
`kokoro` → loads `Provider` from this folder's `adapter.py` and calls
`synthesize(text, voice_id)`. The provider returns the canonical
`SynthesizeResult` envelope (`glc/voice/tts/base.py`); the agent runtime
never sees raw audio frames.

```
text ──► router.synthesize(prefer="default")
            └─► kokoro.adapter.Provider.synthesize(text, voice_id)
                   ├─ config["mock"] present ─► delegate to fake upstream (tests/CI)
                   └─ no mock ─► runner.synthesize() ─► (wav_bytes, 24kHz)
                                     └─ base64 ─► SynthesizeResult(provider="kokoro")
```

Two files do the work:

- `adapter.py` — subclasses `TTSProvider`. One `synthesize` method, two
  branches: delegate to `config["mock"]` when injected, otherwise call
  the real runner and wrap the WAV bytes as a base64 `SynthesizeResult`.
- `runner.py` — hosts the Kokoro `KPipeline` loader. The loaded pipeline
  is cached in a **module-level global**, so the model is loaded once and
  reused for the life of the process.

## Required environment (real path only)

- `uv pip install kokoro` (~300 MB on disk after first call).
- Optional: `GLC_KOKORO_MODEL_DIR` to override the model location
  (default `~/.glc/models/kokoro-82M/`).

CI never touches these — the seven seeded tests run fully offline via
an injected mock, so a fresh checkout with no model download passes.

## Quirks we hit

- `KPipeline(lang_code="a")` downloads weights to
  `~/.cache/huggingface/` on first call. Re-initialising per call would
  pay that cost on every utterance — the pipeline **must** be cached.
  We cache it in `runner._pipeline` and import `runner` lazily inside
  `synthesize` so gateway boot doesn't pay the import cost on installs
  that never use TTS.
- Voice ids are short strings (`af_bella`, `af_sky`, `am_adam`). We
  default to `af_bella` when `voice_id` is `None`.
- The pipeline yields float32 samples at **24 kHz mono**. `runner`
  packs them into a 16-bit PCM WAV byte string; the adapter
  base64-encodes that for transport, `mime="audio/wav"`.
- `cost_usd=0.0` always — Kokoro is local, so nothing lands in the
  ledger as a paid call. (No paid API is used anywhere in the shipped
  code, per the §8 constraint.)

## Trust posture

TTS is an **outbound** voice provider, not an inbound channel, so it
does not classify a sender trust level — that contract belongs to
channel adapters. The provider is a pure function of `(text, voice_id)`
with no side effects beyond producing audio, no filesystem writes
outside a temp WAV buffer, and no network calls on the real path. The
gateway's `policy.yaml` still gates *whether* a `speak` action is
allowed before the router is ever reached; this provider sits below
that decision and only renders audio once allowed.

## Running the real path

Install the Kokoro package and its dependencies (one-time, ~300 MB):

```sh
uv pip install kokoro soundfile
```

Start the gateway:

```sh
cd glc_v1
uv run glc serve
```

Synthesize speech via the HTTP endpoint:

```sh
curl -s -X POST http://localhost:8111/v1/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from Kokoro, the default voice for GLC v1.", "prefer": "default"}' \
  | python -c "
import sys, json, base64, wave, io
r = json.load(sys.stdin)
wav = base64.b64decode(r['audio_b64'])
with open('output.wav', 'wb') as f:
    f.write(wav)
print('Saved output.wav —', r['sample_rate'], 'Hz,', r['mime'])
"
```

This writes `output.wav` (24 kHz mono PCM WAV) to the current directory.
`cost_usd` in the response will be `0.0` — Kokoro is fully local.

The first call triggers `runner._load()`, which downloads model weights
into `~/.cache/huggingface/`. All subsequent calls reuse the cached
`KPipeline` singleton — no re-download, no re-load.

## Tests — `tests/voice/tts/test_kokoro.py`

Seven tests, all green, exercising the mock-delegate branch
(structural + behavioural):

| # | Test | What our code does to pass it |
|--:|------|-------------------------------|
| 1 | `provider_name_matches` | `name = "kokoro"` class attribute. |
| 2 | `synthesize_returns_synthesize_result` | Returns a `SynthesizeResult` with `provider="kokoro"`, non-empty `audio_b64`, `sample_rate>0`. |
| 3 | `synthesize_passes_text_to_upstream` | Delegates the full `text` to the mock; the mock records `text_len`. |
| 4 | `synthesize_records_sample_rate` | Passes the mock's `canned_sample_rate` straight through. |
| 5 | `synthesize_propagates_upstream_error` | We don't swallow exceptions — `TTSError(status=502)` from upstream propagates unchanged. |
| 6 | `synthesize_handles_empty_text` | Empty string is delegated normally; still returns a valid envelope. |
| 7 | `channel_specific_behaviour_pipeline_reuse` | Three calls; because we **delegate** rather than re-instantiate, `pipeline_load_count` stays `1`. The real path mirrors this via the `runner` module-global singleton. |

Run them (with the project env):

```sh
uv run pytest tests/voice/tts/test_kokoro.py -v
```

### Latest verified run

```
collected 7 items

tests/voice/tts/test_kokoro.py::test_provider_name_matches PASSED                  [ 14%]
tests/voice/tts/test_kokoro.py::test_synthesize_returns_synthesize_result PASSED   [ 28%]
tests/voice/tts/test_kokoro.py::test_synthesize_passes_text_to_upstream PASSED     [ 42%]
tests/voice/tts/test_kokoro.py::test_synthesize_records_sample_rate PASSED         [ 57%]
tests/voice/tts/test_kokoro.py::test_synthesize_propagates_upstream_error PASSED   [ 71%]
tests/voice/tts/test_kokoro.py::test_synthesize_handles_empty_text PASSED          [ 85%]
tests/voice/tts/test_kokoro.py::test_channel_specific_behaviour_pipeline_reuse PASSED [100%]

======================= 7 passed in 0.14s =======================
```

**7/7 passed** on branch `kokoro_adapter_imp`. Quality gates on the owned
path are also green: `ruff check` → *All checks passed!* and `mypy` →
*Success: no issues found in 4 source files*.

> All seven run through the injected mock (offline, deterministic) and
> exercise `adapter.py`'s mock-delegate branch only. The end-to-end real
> `runner.synthesize` path is proven separately by the demo video.

### Internal regression tests (bonus, not part of the scored contract)

Four extra tests under [`tests_internal/`](tests_internal/) cover the
real-path branches in `adapter.py`. They live inside the owned path and
are **not** auto-discovered by the default `uv run pytest` invocation
(`pyproject.toml` pins `testpaths = ["tests"]`). Run them explicitly:

```sh
uv run pytest glc/voice/tts/providers/kokoro/tests_internal/ -v
```

| # | Test | What our code does to pass it |
|--:|------|-------------------------------|
| 1 | `none_voice_id_resolved_to_default_before_mock` | Adapter resolves `voice_id=None` → `DEFAULT_VOICE_ID` (`af_bella`) *before* delegating, so both the mock and the real runner always see an explicit voice string. |
| 2 | `runner_generic_exception_wrapped_as_tts_error` | `except Exception` branch in the real path wraps any non-`TTSError` (e.g. `RuntimeError("gpu oom")`) as `TTSError(status=502)` so the gateway's error contract stays consistent. |
| 3 | `runner_empty_audio_raises_tts_error` | If `runner.synthesize` returns `b""` (KPipeline yielded nothing), the adapter refuses to emit a `SynthesizeResult` with 0 bytes and raises `TTSError(status=502)` instead. |
| 4 | `runner_tts_error_passes_through_unchanged` | `except TTSError: raise` branch — a structured error from the runner (e.g. model-load failure at `status=503`) reaches the caller with its original status intact, no re-wrapping. |

#### Latest verified run

```
collected 4 items

glc/voice/tts/providers/kokoro/tests_internal/test_real_path.py::test_none_voice_id_resolved_to_default_before_mock PASSED [ 25%]
glc/voice/tts/providers/kokoro/tests_internal/test_real_path.py::test_runner_generic_exception_wrapped_as_tts_error PASSED [ 50%]
glc/voice/tts/providers/kokoro/tests_internal/test_real_path.py::test_runner_empty_audio_raises_tts_error PASSED [ 75%]
glc/voice/tts/providers/kokoro/tests_internal/test_real_path.py::test_runner_tts_error_passes_through_unchanged PASSED [100%]

============================== 4 passed in 0.26s ==============================
```

**4/4 passed** on branch `kokoro_adapter_imp`.

