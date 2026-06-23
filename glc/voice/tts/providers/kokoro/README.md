# Kokoro-82M — TTS provider (`prefer="default"`)

**Group:** G9 — Group Kokoro · **Slot:** `kokoro` (TTS) · **Owned path:**
`glc/voice/tts/providers/kokoro/`

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

CI never touches these — the seven tests run fully offline against the
mock, so a fresh checkout with no model download passes.

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

## Tests — `tests/voice/tts/test_kokoro.py`

Seven tests, all green. Six structural + one behavioural:

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
