# Gemini Live STT — G-4 Gemini Live STT

Speech-to-Text adapter using Google's **Gemini Live BidiGenerateContent**
WebSocket endpoint. Part of the `glc_v1` gateway, Session 11 assignment.

---

## Architecture

```
Client
  │  POST /v1/transcribe  { audio_b64, mime, prefer="streaming" }
  ▼
Gateway route (glc/routes/transcribe.py)
  │  decodes base64 → raw bytes, dispatches to router
  ▼
STT Router (glc/voice/stt/router.py)
  │  prefer="streaming" → gemini_live provider
  ▼
GeminiLive Provider (adapter.py)
  │
  ├─ mock path  (config["mock"] present)  ←── used by CI / unit tests
  │    records frames, returns canned TranscribeResult
  │
  └─ real path  (production / demo)
       1. Open WebSocket to BidiGenerateContent endpoint
       2. Send BidiGenerateContentSetup frame FIRST
          ┌─ model: gemini-3.1-flash-live-preview
          ├─ responseModalities: ["AUDIO"]
          ├─ outputAudioTranscription: {}   (enables text transcript of reply)
          └─ systemInstruction: "Repeat back exactly what the user says"
       3. Send realtimeInput.audio frame (raw PCM, 16 kHz)
       4. Send audioStreamEnd signal
       5. Collect outputTranscription.text chunks until turnComplete
       6. Return TranscribeResult(text, provider, duration_ms, cost_usd)
```

---

## Channel quirks we hit

Working against the live Gemini BidiGenerateContent API revealed several
undocumented or breaking behaviours:

| Quirk | What happened | How we fixed it |
|---|---|---|
| `inputAudioTranscription: {}` | API returns 1007 "invalid argument" — field rejected entirely | Removed; switched to `outputAudioTranscription` |
| `responseModalities: ["TEXT"]` | 1007 "TEXT not supported by this model" | Only `["AUDIO"]` is accepted by `gemini-3.1-flash-live-preview` |
| `mediaChunks` field | 1007 "realtime_input.media_chunks is deprecated" | Switched to `realtimeInput.audio` field |
| WAV audio format | 1007 "invalid argument" — Gemini Live rejects WAV containers | Strip 44-byte RIFF header in `_build_audio_frame` before sending raw PCM |
| Duplicate transcript | Both `outputTranscription` and `modelTurn.parts[].text` fired on same frame | Changed `if/if/if` to `elif` priority chain — only one source collects per frame |
| GEMINI_API_KEY not found | `glc/main.py` loads `.env` from `ROOT.parent.parent` (two levels up from `glc/`), not from `glc_v1/` | Export key as shell env var: `export GEMINI_API_KEY=...` before running gateway |

---

## How the tests exercise the trust-level boundary

`tests/voice/stt/test_gemini_live.py` — 7 tests using an in-repo mock
(no API key, no network).

| Test | What it checks |
|---|---|
| `test_provider_name_matches` | `provider.name == "gemini_live"` — registry routing depends on this |
| `test_transcribe_returns_transcribe_result` | Return type is `TranscribeResult` — gateway contract |
| `test_transcribe_passes_audio_to_upstream` | Audio bytes reach the upstream unchanged — no silent data loss |
| `test_transcribe_records_duration_ms` | `duration_ms > 0` — latency tracking for scoring |
| `test_transcribe_propagates_upstream_error` | `STTError` bubbles up correctly — gateway turns it into HTTP 400 |
| `test_transcribe_handles_empty_audio` | Empty bytes do not crash — graceful degradation |
| `test_channel_specific_behaviour_setup_frame_first` | **The setup frame must be `frames_sent[0]`** — Gemini Live rejects any session where audio arrives before setup |

The last test is the trust-level boundary check: it enforces the
wire-protocol contract that setup always precedes audio. Breaking this
ordering would cause every real API call to fail with a 1008 policy
violation.

---

## Setup & running

See [SETUP.md](SETUP.md) for full instructions (API key, gateway start,
unit tests, live mic test).
