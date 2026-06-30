# Local Mic Demo Runbook

Notes from the Local Mic implementation and practical demo setup.

## Assignment Scope

Group: Local Mic

Owned paths:

```text
glc/channels/catalogue/local_mic/
glc/channels/catalogue/local_mic/**
```

Local Mic is responsible for this flow:

```text
WAV bytes -> VAD silence skip -> STT router or /v1/transcribe -> ChannelMessage.text
reply text -> TTS router or /v1/speak -> playable audio
```

The Local Mic group does not own the STT provider implementation. In particular:

```text
glc/voice/stt/providers/whisper_cpp/**
```

belongs to Group Whisper.cpp. Any Whisper.cpp provider implementation used for the video is a local-only demo patch and should not be included in the Local Mic PR unless a TA explicitly allows it.

## What The Docs Say

Relevant docs:

```text
docs/ADAPTER_GUIDE.md
docs/VOICE_GUIDE.md
README.md
.github/PULL_REQUEST_TEMPLATE.md
GROUPS.md
```

Important points:

- `docs/ADAPTER_GUIDE.md` says Local Mic's behavior test is `silence.wav` vs `hello.wav`.
- `silence.wav` must produce no envelope.
- `hello.wav` must be transcribed through patched `/v1/transcribe`.
- The resulting `ChannelMessage` must include `text` and `voice_audio_ref`.
- Replies must route through patched `/v1/speak` and reach `mock.play(bytes)`.
- The PR template requires a demo link showing a real upstream path, not just mocks.
- `docs/VOICE_GUIDE.md` says `/v1/transcribe` can route to these STT providers:
  - `prefer="default"` -> Groq Whisper
  - `prefer="local"` -> Whisper.cpp + base model
  - `prefer="streaming"` -> intentionally not for POST in S11
- Those STT providers are outside Group Local Mic scope. Local Mic only calls the shared STT route and consumes the returned transcript.

## Contribution Audit

Base repo:

```text
https://github.com/theschoolofai/glc_v1.git
```

Team fork:

```text
https://github.com/pragsyy1729/glc_v1_g10.git
```

Remote checks performed:

```sh
git ls-remote https://github.com/pragsyy1729/glc_v1_g10.git HEAD refs/heads/main
git ls-remote https://github.com/theschoolofai/glc_v1.git HEAD refs/heads/main
curl -L https://raw.githubusercontent.com/pragsyy1729/glc_v1_g10/main/glc/channels/catalogue/local_mic/adapter.py
curl -L https://raw.githubusercontent.com/theschoolofai/glc_v1/main/glc/channels/catalogue/local_mic/adapter.py
git log --oneline origin/main..origin/feat/local-mic-adapter
```

Findings:

- The team fork `main` branch still had the Local Mic adapter stub when checked.
- The base repo `main` branch also had the Local Mic adapter stub when checked.
- Pragathi's `feat/local-mic-adapter` branch implemented the first Local Mic adapter pass.

Pragathi's actual commits preserved in this PR branch:

```text
c0468be local_mic: implement on_message with VAD, STT, trust classification
59bbf41 local_mic: implement send() with TTS synthesis and rate limit
5e60b6e local_mic: fix mypy override annotation
```

Additional in-scope Local Mic work preserved and refined in this branch:

- VAD gate for silent WAV input.
- trust classification for owner, paired user, and untrusted speaker IDs.
- STT routing from WAV bytes to `ChannelMessage.text`.
- `voice_audio_ref` generation for speech audio.
- TTS routing from reply text to playable audio bytes.
- rate-limit and disconnect handling.
- public-channel allowlist handling.
- assignment-scope demo documentation and PR preparation notes.

## Local Implementation Summary

The Local Mic adapter was implemented in:

```text
glc/channels/catalogue/local_mic/adapter.py
```

It now:

- accepts course-defined mic events with `wav_bytes`
- handles disconnect without raising
- extracts `speaker_id` and `speaker_handle`
- classifies trust through `glc.security.trust_level.classify`
- checks public-channel allowlist behavior
- performs WAV-level RMS VAD before STT
- routes speech bytes through the shared STT router
- stores `voice_audio_ref` as an `art:<sha>` handle
- routes reply text through the shared TTS router
- decodes TTS audio and dispatches it to the mock playback surface
- propagates rate-limit responses

The adapter can use local STT by setting:

```python
Adapter(config={"stt_prefer": "local"})
```

This makes it call the STT router with:

```python
prefer="local"
```

The `prefer="local"` path requires a working Whisper.cpp provider.

## Why Tests Do Not Need A Real Model

The Local Mic tests inject fake STT and TTS providers. That lets CI verify the adapter contract without installing local models or requiring live API keys.

The test flow is:

```text
WAV fixture -> Local Mic adapter -> fake STT -> ChannelMessage
ChannelReply -> fake TTS -> mock.play(bytes)
```

This is correct for the Local Mic group because the adapter owns the routing and envelope behavior, not the actual voice model.

## Local Whisper.cpp Setup Used For Demo

This setup was done locally so the demo can show real STT.

Check whether `whisper-cli` exists:

```sh
command -v whisper-cli
```

Check whether the expected model exists:

```sh
test -f /Users/avi/.glc/models/whisper-base/ggml-base.bin
```

Create GLC local directories:

```sh
mkdir -p /Users/avi/.glc/src /Users/avi/.glc/bin /Users/avi/.glc/models/whisper-base
```

Clone Whisper.cpp:

```sh
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git /Users/avi/.glc/src/whisper.cpp
```

Configure CMake:

```sh
cmake -S /Users/avi/.glc/src/whisper.cpp -B /Users/avi/.glc/src/whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
```

Build:

```sh
cmake --build /Users/avi/.glc/src/whisper.cpp/build -j --config Release
```

Create a stable binary symlink:

```sh
ln -s /Users/avi/.glc/src/whisper.cpp/build/bin/whisper-cli /Users/avi/.glc/bin/whisper-cli
```

Download the base model:

```sh
sh /Users/avi/.glc/src/whisper.cpp/models/download-ggml-model.sh base
```

Create a stable model symlink:

```sh
ln -s /Users/avi/.glc/src/whisper.cpp/models/ggml-base.bin /Users/avi/.glc/models/whisper-base/ggml-base.bin
```

Add GLC local tools to zsh PATH:

```sh
printf '\n# GLC local tools\nexport PATH="/Users/avi/.glc/bin:$PATH"\n' >> /Users/avi/.zshrc
```

Verify:

```sh
zsh -ic 'whisper-cli --version'
```

Expected:

```text
whisper.cpp version: 1.9.1
```

Direct Whisper.cpp smoke test:

```sh
/Users/avi/.glc/bin/whisper-cli -ng \
  -m /Users/avi/.glc/models/whisper-base/ggml-base.bin \
  -f /Users/avi/.glc/src/whisper.cpp/samples/jfk.wav \
  -oj \
  -of /private/tmp/glc-whisper-jfk
```

Note: `-ng` disables GPU. The first non-CPU run failed in the sandbox with a Metal allocation error, while CPU-only worked.

Expected transcript:

```text
And so my fellow Americans ask not what your country can do for you, ask what you can do for your country.
```

## Demo-Only Provider Patch

To make `/v1/transcribe` work locally with `prefer="local"`, a local-only patch was applied to:

```text
glc/voice/stt/providers/whisper_cpp/adapter.py
```

That patch:

- supports test mocks
- skips silent audio before subprocess
- writes audio bytes to a temp file
- runs `whisper-cli -m <model> -f <audio> -oj`
- parses the generated JSON
- returns `TranscribeResult(provider="whisper_cpp")`

Again: this file is outside the Local Mic group's owned path.

Before submitting the Local Mic PR, remove this demo-only change.

## Start The Server

Terminal 1:

```sh
cd /Users/avi/Documents/SessionNotes/Team_Capstone/glc_v1_g10

env UV_CACHE_DIR=/private/tmp/uv-cache uv run glc serve --host 127.0.0.1 --port 8111
```

Expected:

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:8111
```

If a browser hits `/favicon.ico` and the server logs a 404, that is harmless. The actual route we need is `/v1/transcribe`.

## Test Real /v1/transcribe With Local Whisper

Terminal 2:

```sh
cd /Users/avi/Documents/SessionNotes/Team_Capstone/glc_v1_g10

env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "import base64, httpx; audio = base64.b64encode(open('/Users/avi/.glc/src/whisper.cpp/samples/jfk.wav','rb').read()).decode(); r = httpx.post('http://127.0.0.1:8111/v1/transcribe', json={'audio_b64': audio, 'mime': 'audio/wav', 'prefer': 'local'}, timeout=30); print(r.status_code); print(r.json())"
```

Observed output:

```text
200
{'text': 'And so my fellow Americans ask not what your country can do for you, ask what you can do for your country.', 'language': 'en', 'duration_ms': 10500, 'provider': 'whisper_cpp', 'cost_usd': 0.0}
```

This proves:

```text
/v1/transcribe -> prefer local -> whisper_cpp -> local model -> transcript
```

## Test Local Mic Adapter With Local STT

This uses the JFK WAV as a mic-like WAV event:

```sh
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "import asyncio; from pathlib import Path; from glc.channels.catalogue.local_mic.adapter import Adapter; from glc.security.pairing import get_pairing_store; get_pairing_store().force_pair_owner('local_mic', 'owner', user_handle='owner'); audio = Path('/Users/avi/.glc/src/whisper.cpp/samples/jfk.wav').read_bytes(); ev = {'wav_bytes': audio, 'sample_rate': 16000, 'source': 'mic', 'speaker_id': 'owner', 'speaker_handle': 'owner'}; msg = asyncio.run(Adapter(config={'stt_prefer': 'local'}).on_message(ev)); print(msg.channel, msg.channel_user_id, msg.trust_level); print(msg.voice_audio_ref[:16]); print(msg.text)"
```

Observed output:

```text
local_mic owner owner_paired
art:59dfb9a4acb3
And so my fellow Americans ask not what your country can do for you, ask what you can do for your country.
```

This proves:

```text
WAV bytes -> Local Mic adapter -> VAD -> STT router prefer local -> ChannelMessage.text
```

## Generate Speech Without A Microphone

The first custom-audio attempt used:

```sh
say "hello from local mic adapter" -o /tmp/local_mic_demo.aiff
ffmpeg -y -i /tmp/local_mic_demo.aiff -ar 16000 -ac 1 /tmp/local_mic_demo.wav
```

But `ffmpeg` was not installed:

```text
zsh: command not found: ffmpeg
```

Use macOS `afconvert` instead:

```sh
say "hello from local mic adapter" -o /tmp/local_mic_demo.aiff
afconvert -f WAVE -d LEI16@16000 -c 1 /tmp/local_mic_demo.aiff /tmp/local_mic_demo.wav
ls -lh /tmp/local_mic_demo.wav
```

Then run:

```sh
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "import asyncio; from pathlib import Path; from glc.channels.catalogue.local_mic.adapter import Adapter; from glc.security.pairing import get_pairing_store; get_pairing_store().force_pair_owner('local_mic', 'owner', user_handle='owner'); audio = Path('/tmp/local_mic_demo.wav').read_bytes(); ev = {'wav_bytes': audio, 'sample_rate': 16000, 'source': 'mic', 'speaker_id': 'owner', 'speaker_handle': 'owner'}; msg = asyncio.run(Adapter(config={'stt_prefer': 'local'}).on_message(ev)); print(msg.channel, msg.channel_user_id, msg.trust_level); print(msg.voice_audio_ref[:16]); print(msg.text)"
```

## Live Microphone Demo

The assignment uses clip-based STT, not continuous word-by-word streaming. The practical live demo is:

```text
record 4 seconds from mic -> save WAV -> Local Mic adapter -> STT -> print transcript
```

This is near real-time and matches `/v1/transcribe` semantics.

Install SoX if needed:

```sh
brew install sox
```

Record 4 seconds from the microphone:

```sh
rec -r 16000 -c 1 -b 16 /tmp/live_mic.wav trim 0 4
```

Speak while it records, for example:

```text
hello this is a live local mic demo
```

Then run the recorded audio through Local Mic:

```sh
env UV_CACHE_DIR=/private/tmp/uv-cache uv run python -c "import asyncio; from pathlib import Path; from glc.channels.catalogue.local_mic.adapter import Adapter; from glc.security.pairing import get_pairing_store; get_pairing_store().force_pair_owner('local_mic', 'owner', user_handle='owner'); audio = Path('/tmp/live_mic.wav').read_bytes(); ev = {'wav_bytes': audio, 'sample_rate': 16000, 'source': 'mic', 'speaker_id': 'owner', 'speaker_handle': 'owner'}; msg = asyncio.run(Adapter(config={'stt_prefer': 'local'}).on_message(ev)); print(msg.channel, msg.channel_user_id, msg.trust_level); print(msg.voice_audio_ref[:16]); print(msg.text)"
```

In the video, narrate:

```text
This is a live microphone chunk demo. The Local Mic adapter receives WAV bytes,
applies VAD, routes speech to STT with stt_prefer="local", and returns a
ChannelMessage with transcript text and voice_audio_ref.
```

## Validation Commands

Local Mic only:

```sh
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/channels/test_local_mic.py -v
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check glc/channels/catalogue/local_mic
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy glc/channels/catalogue/local_mic
```

Observed:

```text
7 passed
All checks passed
Success: no issues found in 3 source files
```

Local demo with Whisper.cpp patch:

```sh
env UV_CACHE_DIR=/private/tmp/uv-cache uv run pytest tests/channels/test_local_mic.py tests/voice/stt/test_whisper_cpp.py -q
env UV_CACHE_DIR=/private/tmp/uv-cache uv run ruff check glc/channels/catalogue/local_mic glc/voice/stt/providers/whisper_cpp
env UV_CACHE_DIR=/private/tmp/uv-cache uv run mypy glc/channels/catalogue/local_mic glc/voice/stt/providers/whisper_cpp
```

Observed:

```text
14 passed
All checks passed
Success: no issues found in 7 source files
```

## Before Opening The Local Mic PR

Keep only Local Mic files in the PR:

```text
glc/channels/catalogue/local_mic/README.md
glc/channels/catalogue/local_mic/__init__.py
glc/channels/catalogue/local_mic/adapter.py
glc/channels/catalogue/local_mic/DEMO_RUNBOOK.md
```

Remove or revert demo-only changes outside the owned path:

```text
glc/voice/stt/providers/whisper_cpp/adapter.py
```

PR markers:

```text
# Group: Local Mic
# Slot: local_mic
```

Suggested PR demo note:

```text
The Local Mic adapter owns WAV event handling, VAD, trust classification,
allowlist behavior, and routing through the shared STT/TTS layers. The demo
uses a local-only Whisper.cpp provider patch to exercise /v1/transcribe with
prefer="local"; the submitted Local Mic PR only touches the Local Mic slot.
```
