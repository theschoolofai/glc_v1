# Laptop microphone (local voice-first)

This is a **group assignment** in Session 11. The local_mic adapter converts
course-defined microphone events into channel envelopes and converts replies
back into playable speech.

## What you build

Two files under this directory:

- `adapter.py` — subclasses `glc.channels.base.ChannelAdapter` and implements
  `on_message(raw) -> ChannelMessage | None` and `send(reply) -> Any`.
- `schemas.py` — any channel-specific Pydantic types you need.

## Required environment variables

_None._

## Free-tier limits

Free — uses the local mic plus the configured voice providers. By default the
adapter uses the voice router defaults (`groq_whisper` for STT and `kokoro` for
TTS in tests). Set `stt_prefer="local"` in the adapter config to route STT
through Whisper.cpp when that provider is installed.

## Wire-format quirks to expect

PortAudio / sounddevice access on macOS requires the Microphone permission to be
granted to the terminal/host process. Voice activity detection drops silent WAV
input before STT, so `silence.wav` produces no envelope and speech keeps an
`art:<sha>` handle in `voice_audio_ref`.

## Tests you need to pass

The failing tests live at `tests/channels/test_local_mic.py`. They cover:

1. `on_message` builds a valid `ChannelMessage` for owner and stranger inputs.
2. Trust level resolves to `owner_paired` / `user_paired` / `untrusted` correctly.
3. `send` produces a valid wire-format payload and reaches the mock.
4. The adapter handles forced disconnects without raising.
5. Rate-limit responses propagate to the caller as a 429.
6. In public channels with the default `mention_only_in_public: true`, the
   adapter consults the allowlist before processing strangers.

The mock-API fake at `tests/channels/mocks/local_mic_mock.py` is your contract
surface. Do **not** edit the mock or the test file — they are fixed. The
Whisper.cpp provider itself lives under `glc/voice/stt/providers/whisper_cpp/`,
which is owned by Group Whisper.cpp.

## Submission

Open a PR that:

- Adds your `adapter.py` and `schemas.py`.
- Passes `pytest tests/channels/test_local_mic.py`.
- Updates `CLAIMS.md` if you have not already claimed this channel.

CI gates merge through branch protection. A TA reviews before merge.
