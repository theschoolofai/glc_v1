"""Real-API smoke runner for the Gemini Live TTS provider.

Drives the adapter against the live BidiGenerateContent WebSocket so the
PR-required demo video has something to record. The CI test suite covers
the mocked wire format; this script is what proves the real socket works.

Usage
-----
    export GEMINI_API_KEY=...
    uv run python -m glc.voice.tts.providers.gemini_live.smoke "hello world"
    afplay /tmp/gemini_live_out.wav    # macOS
    aplay   /tmp/gemini_live_out.wav   # linux

Prints two timings useful for the latency-budget discussion:

- total_ms        wall-clock duration of the synthesize() call
- audio_ms        duration of the audio that came back
- realtime_factor audio_ms / total_ms. >1 means faster-than-realtime;
                  the Gemini Live free tier typically lands around 1.5-3x
                  on short clips.

It also breaks down cost_usd into the input/output token counts and the
per-leg USD charge so the estimate is auditable, not just a final number.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
import tempfile
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

from glc.voice.tts.base import TTSError
from glc.voice.tts.providers.gemini_live import adapter as adapter_mod
from glc.voice.tts.providers.gemini_live import schemas
from glc.voice.tts.providers.gemini_live.adapter import Provider

DEFAULT_TEXT = "Hello from Gemini Live. This is a smoke test for GLC version one."
DEFAULT_OUT = Path(tempfile.gettempdir()) / "gemini_live_out.wav"


def _audio_duration_ms(wav_bytes: bytes) -> float:
    with wave.open(BytesIO(wav_bytes), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
    return (frames / rate) * 1000.0 if rate else 0.0


def _capture_usage() -> dict[str, Any]:
    """Tap the cost_from_usage chokepoint to record the raw usageMetadata.

    SynthesizeResult only carries the final cost_usd, so to show the token
    counts behind it we wrap the single function that consumes the usage
    frame. Returns a dict the wrapper fills in once synthesize() runs.
    """
    captured: dict[str, Any] = {}
    original = schemas.cost_from_usage

    def spy(usage: dict[str, Any] | None) -> float:
        captured["usage"] = usage
        return original(usage)

    # The adapter did `from schemas import cost_from_usage`, binding its own
    # reference, so patch both the module symbol and the adapter's copy.
    schemas.cost_from_usage = spy  # type: ignore[assignment]
    adapter_mod.cost_from_usage = spy  # type: ignore[assignment]
    return captured


def _print_cost_breakdown(usage: dict[str, Any] | None) -> None:
    if not usage:
        print("cost_breakdown:  no usageMetadata frame arrived (cost stays 0.0)")
        return
    prompt = schemas._usage_token_count(usage, "promptTokenCount", "prompt_token_count")
    response = schemas._usage_token_count(
        usage,
        "responseTokenCount",
        "response_token_count",
        "candidatesTokenCount",
        "candidates_token_count",
    )
    in_usd = prompt * schemas.GEMINI_LIVE_INPUT_USD_PER_MTOK / 1_000_000
    out_usd = response * schemas.GEMINI_LIVE_OUTPUT_AUDIO_USD_PER_MTOK / 1_000_000
    print(f"input_tokens:    {prompt:>7,}  @ ${schemas.GEMINI_LIVE_INPUT_USD_PER_MTOK}/Mtok = ${in_usd:.6f}")
    print(
        f"output_tokens:   {response:>7,}  @ ${schemas.GEMINI_LIVE_OUTPUT_AUDIO_USD_PER_MTOK}/Mtok = ${out_usd:.6f}"
    )


async def _run(text: str, voice_id: str | None, out: Path) -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("error: GEMINI_API_KEY is not set", file=sys.stderr)
        return 2

    provider = Provider()
    captured = _capture_usage()

    started = time.perf_counter()
    try:
        result = await provider.synthesize(text, voice_id=voice_id)
    except TTSError as e:
        print(f"error: TTSError status={e.status}: {e}", file=sys.stderr)
        return 1
    total_ms = (time.perf_counter() - started) * 1000.0

    wav_bytes = base64.b64decode(result.audio_b64)
    out.write_bytes(wav_bytes)
    audio_ms = _audio_duration_ms(wav_bytes)
    rtf = audio_ms / total_ms if total_ms else 0.0

    print(f"provider:        {result.provider}")
    print(f"mime:            {result.mime}")
    print(f"sample_rate:     {result.sample_rate} Hz")
    _print_cost_breakdown(captured.get("usage"))
    print(f"cost_usd:        {result.cost_usd:.6f}")
    print(f"wav_bytes:       {len(wav_bytes):,}")
    print(f"total_ms:        {total_ms:7.1f}")
    print(f"audio_ms:        {audio_ms:7.1f}")
    print(f"realtime_factor: {rtf:7.2f}x")
    print(f"wrote:           {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m glc.voice.tts.providers.gemini_live.smoke",
        description="Drive the Gemini Live TTS adapter against the real WebSocket.",
    )
    parser.add_argument("text", nargs="?", default=DEFAULT_TEXT)
    parser.add_argument(
        "--voice",
        default=None,
        help="prebuilt voice name (e.g. Puck, Charon, Kore). Currently passed through but adapter ignores it.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    return asyncio.run(_run(args.text, args.voice, args.out))


if __name__ == "__main__":
    sys.exit(main())
