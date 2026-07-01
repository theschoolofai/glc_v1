"""Persistent seen-UID deduplication for IMAP.

Why this is critical for IMAP (and has no equivalent in REST-based email APIs):
  After a crash or IDLE reconnect, IMAP SEARCH UNSEEN returns every unread
  UID in the mailbox — including messages already processed in the current
  session. Without a persistent seen-set the adapter would re-deliver old
  messages to the agent on every restart.

The seen-set is stored in SQLite so it survives process restarts at negligible
cost. Entries older than 7 days are pruned automatically to bound the
database size.

Thread-safety: all writes go through a module-level threading.Lock so the
tracker is safe to use from concurrent coroutines (asyncio + threads).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_DEFAULT_PATH = Path(os.path.expanduser("~/.glc/imap_uids.sqlite"))


class UidTracker:
    """SQLite-backed store of seen IMAP UIDs.

    Usage:
        tracker = UidTracker()
        if not tracker.is_seen("INBOX", uid):
            process(uid)
            tracker.mark_seen("INBOX", uid)
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        env_path = os.getenv("GLC_IMAP_UID_DB")
        self._path: Path = Path(env_path) if env_path else (Path(db_path) if db_path else _DEFAULT_PATH)
        self._lock = threading.Lock()
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS seen_uids (
                    mailbox TEXT    NOT NULL,
                    uid     INTEGER NOT NULL,
                    seen_at REAL    NOT NULL,
                    PRIMARY KEY (mailbox, uid)
                )"""
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_seen(self, mailbox: str, uid: int) -> bool:
        """Return True if (mailbox, uid) has been marked seen."""
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM seen_uids WHERE mailbox=? AND uid=?",
                (mailbox, uid),
            ).fetchone()
            return row is not None

    def mark_seen(self, mailbox: str, uid: int) -> None:
        """Record (mailbox, uid) as processed. Idempotent."""
        with self._lock:
            with self._conn() as c:
                c.execute(
                    "INSERT OR IGNORE INTO seen_uids (mailbox, uid, seen_at) VALUES (?,?,?)",
                    (mailbox, uid, time.time()),
                )

    def cleanup_old(self, days: int = 7) -> int:
        """Prune entries older than *days* days. Returns count removed."""
        cutoff = time.time() - days * 86_400
        with self._lock:
            with self._conn() as c:
                cur = c.execute("DELETE FROM seen_uids WHERE seen_at < ?", (cutoff,))
                return cur.rowcount

    def reset(self, mailbox: str) -> None:
        """Remove all seen UIDs for *mailbox* (for testing / fresh start)."""
        with self._lock:
            with self._conn() as c:
                c.execute("DELETE FROM seen_uids WHERE mailbox=?", (mailbox,))
