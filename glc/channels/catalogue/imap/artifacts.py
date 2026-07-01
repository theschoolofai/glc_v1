"""Ephemeral artifact store for IMAP/SMTP attachment blobs.

All MIME attachment types are supported (application/*, image/*, audio/*,
video/*). Blobs are stored under ~/.glc/artifacts/<sha256[:16]> and expire
after 5 minutes (via cleanup_expired()).

Security: the artifact ref format is "art:<16-hex>". Any ref that does not
match exactly 16 lowercase hex characters is rejected with ValueError before
any file I/O occurs — this blocks path-traversal attacks.

Thread-safety: a module-level lock serialises all writes and deletes.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
_DEFAULT_DIR = Path(os.path.expanduser("~/.glc/artifacts"))
_LOCK = threading.Lock()


@dataclass
class _Meta:
    mime: str
    filename: str
    stored_at: float


class ArtifactStore:
    """Disk-backed ephemeral store for attachment blobs.

    Usage:
        store = ArtifactStore()
        ref = store.store(data, mime="application/pdf", filename="doc.pdf")
        # ref == "art:<16-hex>"
        data = store.get(ref)
        store.remove(ref)
        store.cleanup_expired(ttl=300)   # prune blobs older than 5 min
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        env_dir = os.getenv("GLC_ARTIFACTS_DIR")
        self._base: Path = Path(env_dir) if env_dir else (Path(base_dir) if base_dir else _DEFAULT_DIR)
        self._meta: dict[str, _Meta] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    @staticmethod
    def _validate_ref(ref: str) -> str:
        """Return the bare 16-hex key or raise ValueError."""
        if not isinstance(ref, str) or not ref.startswith("art:"):
            raise ValueError(f"Invalid artifact ref (must start with 'art:'): {ref!r}")
        key = ref.removeprefix("art:")
        if not _HEX16_RE.match(key):
            raise ValueError(f"Invalid artifact key (must be exactly 16 lowercase hex chars): {key!r}")
        return key

    def _path(self, key: str) -> Path:
        return self._base / key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        data: bytes,
        mime: str = "application/octet-stream",
        filename: str = "",
    ) -> str:
        """Persist *data* to disk and return its artifact ref "art:<key>".

        Storing the same bytes twice is idempotent (same SHA256 key).
        """
        key = self._key(data)
        self._base.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        with _LOCK:
            path.write_bytes(data)
            self._meta[key] = _Meta(mime=mime, filename=filename, stored_at=time.time())
        return f"art:{key}"

    def get(self, ref: str) -> bytes | None:
        """Return the raw bytes for *ref*, or None if not found."""
        key = self._validate_ref(ref)
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def remove(self, ref: str) -> None:
        """Delete the blob for *ref*. No-op if already gone."""
        key = self._validate_ref(ref)
        path = self._path(key)
        with _LOCK:
            if path.exists():
                path.unlink()
            self._meta.pop(key, None)

    def cleanup_expired(self, ttl: int = 300) -> int:
        """Remove blobs stored more than *ttl* seconds ago.

        Returns the number of blobs removed.
        """
        cutoff = time.time() - ttl
        removed = 0
        with _LOCK:
            expired_keys = [k for k, m in self._meta.items() if m.stored_at < cutoff]
            for key in expired_keys:
                path = self._path(key)
                if path.exists():
                    path.unlink()
                del self._meta[key]
                removed += 1
        return removed
