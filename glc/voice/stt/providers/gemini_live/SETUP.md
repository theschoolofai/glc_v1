# Gemini Live STT — Setup & Test Guide

## 1. Prerequisites

Add your Gemini API key to `.env` in the project root (`glc_v1/.env`):

```
GEMINI_API_KEY=your-key-here
```

Get a free key at https://aistudio.google.com/app/apikey

Install required audio libraries (one-time):

```bash
uv add sounddevice soundfile
```

## 2. Start the gateway

```bash
uv run glc serve        # starts on http://localhost:8111
```

Wait until you see `Uvicorn running on http://0.0.0.0:8111`.

## 3. Run unit tests (no API key needed)

```bash
uv run pytest tests/voice/stt/test_gemini_live.py -v
```

All 7 tests should pass.

## 4. Live mic → transcript test

Open a **second terminal** (gateway must stay running in the first).
Export your key, then paste and run the script below:

```bash
export GEMINI_API_KEY="your-key-here"

uv run python - << 'EOF'
import base64, io, json, urllib.request, urllib.error
import sounddevice as sd
import soundfile as sf

SAMPLE_RATE = 16000
DURATION = 5

print("Recording for 5 seconds... speak now!")
audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
sd.wait()
print("Done. Sending to Gemini Live STT...")

buf = io.BytesIO()
sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
audio_b64 = base64.b64encode(buf.getvalue()).decode()

payload = json.dumps({"audio_b64": audio_b64, "mime": "audio/wav", "prefer": "streaming"}).encode()
req = urllib.request.Request(
    "http://localhost:8111/v1/transcribe",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    print("Transcript:", result["text"])
    print("provider=" + result["provider"] + "  duration_ms=" + str(result["duration_ms"]))
except urllib.error.HTTPError as e:
    print("HTTP " + str(e.code) + " error: " + e.read().decode())
EOF
```

Expected output:

```
Recording for 5 seconds... speak now!
Done. Sending to Gemini Live STT...
Transcript: <exactly what you said>
provider=gemini_live  duration_ms=XXXX
```
