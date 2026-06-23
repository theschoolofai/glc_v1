# whisper.cpp (local, offline)

Group assignment in Session 11. Implement the local STT provider using
whisper.cpp's `whisper-cli` binary and the base GGML model.

## What you build

- `adapter.py` — subclass `STTProvider`, invoke `whisper-cli -m <model>
  -f <audio> -oj`, parse the JSON output, return a `TranscribeResult`.

## Required environment

- A `whisper-cli` binary on PATH (build from
  https://github.com/ggerganov/whisper.cpp).
- A base GGML model at `~/.glc/models/whisper-base/ggml-base.bin`
  (downloaded by `./daemon/install.sh --models`).

## Quirks

- The CLI writes its JSON next to the input file as `<input>.json`.
- Audio inputs longer than ~30s are VAD-trimmed first — long silences
  inflate latency without improving the transcript. The trim uses
  whisper.cpp's threshold-based VAD (`--vad -vt N`, default 0.5,
  override via `GLC_WHISPER_VAD_THRESHOLD`); no Silero model file is
  needed.
- The base model is ~150 MB on disk and runs in real-time on Apple
  Silicon. The small model is faster but degrades on accented speech.

## Tests you need to pass

`tests/voice/stt/test_whisper_cpp.py` — six structural tests plus
`test_channel_specific_behaviour_vad_trim_silence`: the adapter must
NOT invoke `whisper-cli` when the input is silent (the mock detects
silence by zero-amplitude WAV bytes). Adapters that always shell out
will blow CI runtime budgets in production.
