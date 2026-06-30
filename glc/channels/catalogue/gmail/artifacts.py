"""Ephemeral artifact store for the Gmail adapter.

Stores attachment bytes temporarily under ~/.glc/artifacts/<hash>
while the agent processes them. Once processing is complete, the
caller should call remove(ref) or cleanup_session() to delete them.

The art:<hash> reference in ChannelMessage.attachments resolves to
bytes via get(ref).
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

DEFAULT_DIR = Path(os.path.expanduser("~/.glc/artifacts"))

# Auto-expire artifacts older than this (seconds)
MAX_AGE = 300  # 5 minutes


def _resolve_dir() -> Path:
    d = Path(os.getenv("GLC_ARTIFACTS_DIR", str(DEFAULT_DIR)))
    d.mkdir(parents=True, exist_ok=True)
    return d


def store(data: bytes, filename: str = "") -> str:
    """Store bytes temporarily and return the art:<hash> reference."""
    sha = hashlib.sha256(data).hexdigest()[:16]
    ref = f"art:{sha}"

    artifact_dir = _resolve_dir()
    artifact_path = artifact_dir / sha

    if not artifact_path.exists():
        artifact_path.write_bytes(data)

        meta_path = artifact_dir / f"{sha}.meta"
        meta_path.write_text(f"filename={filename}\nsize={len(data)}\ncreated={time.time()}\n")

    return ref


def _validate_ref(ref: str) -> str | None:
    """Extract and validate the hash from an art: reference."""
    if not ref.startswith("art:"):
        return None
    sha = ref[4:]
    if not re.fullmatch(r"[a-f0-9]{16}", sha):
        return None
    return sha


def get(ref: str) -> bytes | None:
    """Resolve an art:<hash> reference back to bytes."""
    sha = _validate_ref(ref)
    if sha is None:
        return None
    artifact_path = _resolve_dir() / sha
    if artifact_path.exists():
        return artifact_path.read_bytes()
    return None


def get_path(ref: str) -> Path | None:
    """Get the filesystem path for an artifact."""
    sha = _validate_ref(ref)
    if sha is None:
        return None
    artifact_path = _resolve_dir() / sha
    if artifact_path.exists():
        return artifact_path
    return None


def remove(ref: str) -> bool:
    """Remove an artifact after processing is complete."""
    sha = _validate_ref(ref)
    if sha is None:
        return False
    artifact_dir = _resolve_dir()
    removed = False
    for path in [artifact_dir / sha, artifact_dir / f"{sha}.meta"]:
        if path.exists():
            path.unlink()
            removed = True
    return removed


def cleanup_session(refs: list[str]) -> int:
    """Remove all artifacts from a processing session."""
    count = 0
    for ref in refs:
        if remove(ref):
            count += 1
    return count


def cleanup_expired() -> int:
    """Remove artifacts older than MAX_AGE. Call periodically."""
    artifact_dir = _resolve_dir()
    now = time.time()
    count = 0
    for meta_path in artifact_dir.glob("*.meta"):
        try:
            content = meta_path.read_text()
            for line in content.splitlines():
                if line.startswith("created="):
                    created = float(line.split("=")[1])
                    if now - created > MAX_AGE:
                        sha = meta_path.stem
                        data_path = artifact_dir / sha
                        if data_path.exists():
                            data_path.unlink()
                        meta_path.unlink()
                        count += 1
                    break
        except (ValueError, OSError):
            continue
    return count
