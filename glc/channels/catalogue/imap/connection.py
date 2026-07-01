"""IMAP connection manager — LOGIN, SELECT, IDLE, and reconnect with backoff.

IMAP connections are long-lived TCP sessions. Unlike REST APIs they can
drop silently (NAT timeout, server restart, flaky network) without raising
an error until the next command is sent. This module handles:

  - SSL/TLS connection to IMAP port 993 (imaplib.IMAP4_SSL)
  - SEARCH UNSEEN → FETCH UID RFC822 for polling
  - STORE +FLAGS \\Seen after successful processing
  - IDLE command for push-like behaviour (server notifies on new mail)
  - Exponential reconnect backoff: 1 → 2 → 4 → 8 → 16 → 32 → 60 seconds

Mock mode
---------
When a mock object is injected (tests), no real TCP socket is opened.
  - connect() / close() / mark_seen() / idle_*() are no-ops.
  - fetch_unseen() returns mock.inbound_events (list of raw-bytes dicts).
  - reconnect() delegates to mock.pop_disconnect() for the signal.
"""

from __future__ import annotations

import imaplib
import logging
import ssl
import time
from typing import Any

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Exponential backoff delays in seconds, capped at 60.
_BACKOFF = [1, 2, 4, 8, 16, 32, 60]


class ImapConnection:
    """Manages a single IMAP SSL session with automatic reconnection.

    Usage (production):
        conn = ImapConnection(host="imap.zoho.in", port=993,
                              user="bot@your-domain.com", password="<app-password>")
        conn.connect()
        for ev in conn.fetch_unseen():
            process(ev)
            conn.mark_seen(ev["uid"])
        conn.close()

    Usage (tests — mock injected):
        conn = ImapConnection(..., mock=imap_mock)
        # No TCP; fetch_unseen() returns mock.inbound_events directly.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        mailbox: str = "INBOX",
        mock: Any = None,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.mailbox = mailbox
        self.mock = mock
        self._conn: imaplib.IMAP4_SSL | None = None
        self._idle_active = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open SSL connection, LOGIN, SELECT mailbox."""
        if self.mock is not None:
            return  # mock mode — no real TCP
        if certifi is not None:
            ctx = ssl.create_default_context(cafile=certifi.where())
        else:
            ctx = ssl.create_default_context()
        self._conn = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=ctx)
        self._conn.login(self.user, self.password)
        self._conn.select(self.mailbox)
        log.info("[IMAP ] Connected to %s:%s", self.host, self.port)
        log.info("[IMAP ] Watching %s", self.mailbox)

    def fetch_unseen(self) -> list[dict[str, Any]]:
        """Return unseen messages as a list of {"uid": int, "raw": bytes}.

        In mock mode: returns mock.inbound_events as-is.
        In live mode: SEARCH UNSEEN → FETCH (RFC822) for each UID.
        """
        if self.mock is not None:
            return list(self.mock.inbound_events)

        assert self._conn is not None, "call connect() first"
        _, data = self._conn.search(None, "UNSEEN")
        uid_list: list[bytes] = data[0].split() if data[0] else []
        messages: list[dict[str, Any]] = []
        for uid_bytes in uid_list:
            uid = int(uid_bytes)
            _, msg_data = self._conn.fetch(str(uid), "(RFC822)")
            for part in msg_data:
                if isinstance(part, tuple):
                    messages.append({"uid": uid, "raw": part[1]})
        return messages

    def mark_seen(self, uid: int) -> None:
        """Set \\Seen flag on the server for *uid*."""
        if self.mock is not None or self._conn is None:
            return
        self._conn.store(str(uid), "+FLAGS", "\\Seen")

    def idle_start(self) -> None:
        """Send IDLE command — server will push EXISTS/RECENT notifications."""
        if self.mock is not None or self._conn is None:
            return
        try:
            self._conn.send(b"A001 IDLE\r\n")
            self._idle_active = True
            log.debug("[IMAP ] IDLE started")
        except Exception as exc:
            log.warning("[IMAP ] IDLE start failed: %s", exc)

    def idle_stop(self) -> None:
        """Send DONE to exit IDLE mode before issuing the next command."""
        if self.mock is not None or self._conn is None:
            return
        if self._idle_active:
            try:
                self._conn.send(b"DONE\r\n")
                log.debug("[IMAP ] IDLE stopped")
            except Exception:
                pass
            self._idle_active = False

    def reconnect(self) -> None:
        """Close the current session and reconnect with exponential backoff.

        Attempts the *_BACKOFF* sequence (1 → 2 → 4 → … → 60 s).
        Logs a final error if all attempts fail.
        """
        self.close()
        for delay in _BACKOFF:
            log.warning("[IMAP ] Reconnecting in %ds…", delay)
            time.sleep(delay)
            try:
                self.connect()
                log.info("[IMAP ] Reconnected successfully")
                return
            except Exception as exc:
                log.warning("[IMAP ] Reconnect attempt failed: %s", exc)
        log.error("[IMAP ] All reconnect attempts exhausted — giving up")

    def close(self) -> None:
        """Gracefully LOGOUT and close the TCP connection."""
        if self.mock is not None or self._conn is None:
            return
        try:
            self._idle_active = False
            self._conn.logout()
        except Exception:
            pass
        self._conn = None
        log.info("[IMAP ] Connection closed")
