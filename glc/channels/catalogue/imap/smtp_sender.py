"""Stateless SMTP sender with STARTTLS and SMTP 421 → 429 normalisation.

Design: stateless (open-per-send)
----------------------------------
Zoho Mail (and most SMTP servers) silently close idle connections after
approximately 5 minutes. Keeping a persistent connection open in a
long-running process causes stale-socket errors on the first send after
an idle period. Opening a fresh SMTP session per send avoids this
entirely at negligible cost (TLS handshake ~50 ms on LAN, ~200 ms WAN).

SMTP back-pressure
------------------
SMTP servers signal transient unavailability with 4xx response codes.
421 ("Service not available, try later") is the canonical back-pressure
signal. This module normalises any SMTP 421 to the dict
    {"status": 429, "error": "<smtp message>"}
so callers can apply standard rate-limit handling without knowing SMTP
response codes.

All other SMTP errors are re-raised to the caller.
"""

from __future__ import annotations

import logging
import smtplib
import uuid
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)


class SmtpSender:
    """Stateless SMTP sender.

    Usage:
        sender = SmtpSender(host="smtp.zoho.in", port=587,
                            user="bot@your-domain.com", password="<app-password>",
                            bot_from="bot@your-domain.com")
        result = sender.send(to="user@example.com", raw_bytes=msg_bytes)
        # {"status": 250, "message_id": "<...>"}
        # {"status": 429, "error": "..."} on SMTP 421
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        bot_from: str,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.bot_from = bot_from

    @contextmanager
    def _session(self):
        """Open an SMTP session with EHLO → STARTTLS → AUTH, then close."""
        smtp = smtplib.SMTP(self.host, self.port, timeout=30)
        try:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(self.user, self.password)
            yield smtp
        finally:
            try:
                smtp.quit()
            except Exception:
                pass

    def send(self, to: str, raw_bytes: bytes) -> dict[str, Any]:
        """Send pre-built RFC 5322 bytes via SMTP STARTTLS.

        Returns:
            {"status": 250, "message_id": "<...>"}  — on success
            {"status": 429, "error": "..."}          — on SMTP 421 (try later)

        Raises smtplib.SMTPException for all other SMTP errors.
        """
        msg_id = f"<{uuid.uuid4().hex}@glc>"
        try:
            with self._session() as smtp:
                smtp.sendmail(self.bot_from, to, raw_bytes)
            log.info("[SMTP ] Delivered to %s — 250 OK", to)
            return {"status": 250, "message_id": msg_id}
        except smtplib.SMTPResponseException as exc:
            if exc.smtp_code == 421:
                log.warning("[SMTP ] 421 back-pressure sending to %s: %s", to, exc)
                return {"status": 429, "error": str(exc)}
            raise
