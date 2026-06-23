"""whisper.cpp wrapper shim.

Expects a `whisper-cli` binary on PATH and a base model at
~/.glc/models/whisper-base/ggml-base.bin. Invokes the binary as a
subprocess, parses the JSON output, returns (text, language,
duration_ms). The model download is handled by the install script.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path

MODEL_DIR = Path(os.path.expanduser(os.getenv("GLC_WHISPER_MODEL_DIR", "~/.glc/models/whisper-base")))
MODEL_FILE = MODEL_DIR / "ggml-base.bin"


DEFAULT_VAD_THRESHOLD = 0.5


def _build_argv(cli: str, model: Path, audio_path: Path, vad: bool) -> list[str]:
    """Build the whisper-cli argv, appending native VAD flags when asked.

    VAD is threshold-based (`--vad -vt N`) rather than model-based: no
    separate Silero model file is required, just a speech-probability cut.
    """
    argv = [cli, "-m", str(model), "-f", str(audio_path), "-oj"]
    if vad:
        argv += ["--vad", "-vt", f"{DEFAULT_VAD_THRESHOLD}"]
    return argv


def run_whisper_cpp(audio: bytes, mime: str, vad: bool = False) -> tuple[str, str, int]:
    cli = shutil.which("whisper-cli") or shutil.which("whisper.cpp")
    if cli is None:
        raise RuntimeError(
            "whisper-cli binary not found on PATH. Install whisper.cpp "
            "and place its 'whisper-cli' binary on PATH, or use "
            "prefer='default' for Groq."
        )
    if not MODEL_FILE.exists():
        raise RuntimeError(
            f"whisper base model not found at {MODEL_FILE}. Run "
            "`daemon/install.sh --models` or download manually."
        )
    suffix = ".wav" if "wav" in mime else ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio)
        audio_path = Path(f.name)
    try:
        out = subprocess.run(
            _build_argv(cli, MODEL_FILE, audio_path, vad),
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        audio_path.unlink(missing_ok=True)
    json_path = audio_path.with_suffix(audio_path.suffix + ".json")
    if json_path.exists():
        d = json.loads(json_path.read_text())
        json_path.unlink(missing_ok=True)
        segments = d.get("transcription") or d.get("segments") or []
        text = " ".join((s.get("text") or "").strip() for s in segments).strip()
        language = d.get("language") or "en"
        duration_ms = int(segments[-1].get("offsets", {}).get("to", 0)) if segments else 0
        return text, language, duration_ms
    return out.stdout.strip(), "en", 0
