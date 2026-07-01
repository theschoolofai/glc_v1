"""Pure MIME tree walker — zero I/O, zero side-effects.

parse(raw_bytes: bytes) -> ParsedEmail | None

All logic is contained in pure functions that take bytes or parsed
email.Message objects and return plain Python values. No file I/O,
no network calls, no global state. This makes the module trivially
unit-testable in isolation.

Text extraction rules
---------------------
1. Prefer text/plain — always walk the MIME tree first for a text/plain part.
2. HTML fallback — if only text/html exists, strip all HTML tags and return
   the resulting plain text. This protects the agent context from HTML/JS
   injection while still surfacing the human-readable message body.
3. Multipart/alternative — handled naturally by walking the full tree
   (both text/plain and text/html will be found; plain wins).

Attachment extraction
---------------------
All non-text MIME parts are extracted as raw bytes dicts:
    {"mime": str, "filename": str, "data": bytes}
The caller (adapter) is responsible for storing these in ArtifactStore.
"""

from __future__ import annotations

import email
import email.policy
import re
from email.message import EmailMessage

from glc.channels.catalogue.imap.schemas import ParsedEmail

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_EXCESS_WS_RE = re.compile(r"\s+")

# MIME types that carry human-readable text — not treated as attachments.
_TEXT_TYPES = {"text/plain", "text/html"}


# ------------------------------------------------------------------
# Low-level helpers (pure functions)
# ------------------------------------------------------------------


def _strip_display_name(addr: str) -> str:
    """Return the bare RFC 5321 email address from a display-name header.

    Examples:
        'Alice <alice@example.com>'  →  'alice@example.com'
        'alice@example.com'          →  'alice@example.com'
        ''                           →  ''
    """
    addr = addr.strip()
    if "<" in addr and addr.endswith(">"):
        return addr[addr.index("<") + 1 : -1].strip()
    return addr


def _strip_html_tags(html: str) -> str:
    """Remove all HTML tags and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", html)
    return _EXCESS_WS_RE.sub(" ", text).strip()


def _walk_text(msg: EmailMessage) -> tuple[str, str]:
    """Walk the MIME tree and return (text_plain, text_html).

    Stops at the first text/plain part (prefer plain over html).
    Captures the first text/html part as a fallback.
    """
    plain = ""
    html = ""

    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not plain:
                try:
                    plain = part.get_content() or ""
                except Exception:
                    pass
            elif ct == "text/html" and not html:
                try:
                    html = part.get_content() or ""
                except Exception:
                    pass
    else:
        ct = msg.get_content_type()
        try:
            content = msg.get_content() or ""
        except Exception:
            content = ""
        if ct == "text/plain":
            plain = content
        elif ct == "text/html":
            html = content

    return plain, html


def _walk_attachments(msg: EmailMessage) -> list[dict]:
    """Return all non-text MIME parts as raw-bytes dicts.

    Each entry: {"mime": str, "filename": str, "data": bytes}

    Skips multipart container parts and any part whose payload
    cannot be decoded (malformed MIME is tolerated, not raised).
    """
    attachments: list[dict] = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct in _TEXT_TYPES or part.get_content_maintype() == "multipart":
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            payload = None
        data: bytes | None = payload if isinstance(payload, bytes) else None
        if not data:
            continue
        attachments.append(
            {
                "mime": ct,
                "filename": part.get_filename() or "",
                "data": data,
            }
        )
    return attachments


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def parse(raw_bytes: bytes) -> ParsedEmail | None:
    """Parse RFC 822 bytes into a :class:`ParsedEmail`.

    Returns ``None`` if *raw_bytes* is empty; never raises on malformed
    input (the stdlib email parser is extremely fault-tolerant).

    The returned ``ParsedEmail.sender`` is always a bare email address
    with any display name stripped.
    """
    if not raw_bytes:
        return None

    try:
        msg: EmailMessage = email.message_from_bytes(  # type: ignore[assignment]
            raw_bytes, policy=email.policy.default
        )
    except Exception:
        return None

    # Headers
    sender_raw = msg.get("From", "")
    sender = _strip_display_name(sender_raw)
    subject = msg.get("Subject", "") or ""
    message_id = (msg.get("Message-ID") or "").strip() or None
    references = (msg.get("References") or "").strip() or None
    in_reply_to = (msg.get("In-Reply-To") or "").strip() or None

    # Body
    plain, html = _walk_text(msg)
    # HTML-only fallback: strip tags so no HTML/JS reaches the agent
    if not plain and html:
        plain = _strip_html_tags(html)

    attachments = _walk_attachments(msg)

    return ParsedEmail(
        uid=None,  # injected by the adapter from the IMAP FETCH envelope
        message_id=message_id,
        sender=sender,
        subject=subject,
        text=plain,
        html=html,
        attachments=attachments,
        references=references,
        in_reply_to=in_reply_to,
    )
