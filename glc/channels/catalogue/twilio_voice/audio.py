"""Audio conversion for the twilio_voice adapter.

Twilio Media Streams deliver headerless **G.711 mu-law** ("PCMU") at 8 kHz
mono. Speech-to-text providers (Groq Whisper, whisper.cpp) expect a
self-describing PCM container — whisper.cpp specifically wants 16 kHz mono
WAV. This module turns the raw mu-law payload into a 16 kHz mono PCM WAV.

No third-party dependencies and no `audioop`: the stdlib `audioop` module was
removed in Python 3.13 (PEP 594), and this project supports `>=3.11`, so we
decode mu-law with a precomputed table instead.

Reference: ITU-T G.711 mu-law; Sun Microsystems reference decoder.
"""

from __future__ import annotations

import io
import sys
import wave
from array import array

TWILIO_SAMPLE_RATE = 8000  # Twilio Media Streams are always 8 kHz mono mu-law.
TARGET_SAMPLE_RATE = 16000  # whisper.cpp requires 16 kHz mono PCM.
WAV_MIME = "audio/wav"

_BIAS = 0x84  # G.711 mu-law bias (132).


def _build_decode_table() -> list[int]:
    """Precompute the 256-entry mu-law → signed-16-bit-PCM lookup table."""
    table: list[int] = []
    for byte in range(256):
        u = ~byte & 0xFF
        t = ((u & 0x0F) << 3) + _BIAS
        t <<= (u & 0x70) >> 4
        table.append((_BIAS - t) if (u & 0x80) else (t - _BIAS))
    return table


_DECODE_TABLE = _build_decode_table()


def decode_mulaw(payload: bytes) -> array:
    """Decode G.711 mu-law bytes into an array of signed 16-bit PCM samples."""
    return array("h", (_DECODE_TABLE[b] for b in payload))


def resample(samples: array, src_rate: int, dst_rate: int) -> array:
    """Linear-interpolation resample. Adequate for speech handed to STT;
    not a brick-wall filter, but Whisper-class models are robust to it."""
    if src_rate == dst_rate or len(samples) == 0:
        return samples
    n_out = max(1, round(len(samples) * dst_rate / src_rate))
    ratio = src_rate / dst_rate
    out = array("h", bytes(2 * n_out))
    last = len(samples) - 1
    for i in range(n_out):
        pos = i * ratio
        idx = int(pos)
        frac = pos - idx
        s0 = samples[idx]
        s1 = samples[idx + 1] if idx < last else s0
        out[i] = int(s0 + (s1 - s0) * frac)
    return out


def _pcm_le_bytes(samples: array) -> bytes:
    """Serialise samples as little-endian (WAV byte order) regardless of host."""
    if sys.byteorder == "big":
        swapped = array("h", samples)
        swapped.byteswap()
        return swapped.tobytes()
    return samples.tobytes()


def mulaw_to_wav(
    payload: bytes,
    *,
    src_rate: int = TWILIO_SAMPLE_RATE,
    dst_rate: int = TARGET_SAMPLE_RATE,
) -> bytes:
    """Convert raw Twilio mu-law audio into a self-contained mono PCM WAV.

    Returns a complete WAV file (RIFF header + PCM data). An empty payload
    yields a valid, zero-frame WAV so callers never special-case silence.
    """
    samples = resample(decode_mulaw(payload), src_rate, dst_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(dst_rate)
        wav.writeframes(_pcm_le_bytes(samples))
    return buf.getvalue()
