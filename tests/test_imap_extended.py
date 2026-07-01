"""Extended IMAP/SMTP adapter tests — edge cases and module-level verification.

Covers IMAP/SMTP-specific behaviour beyond the 7 CI-required tests in
tests/channels/test_imap.py:

  Group A — Input robustness (tests 1-3)
      Malformed, missing, and corrupt raw bytes.

  Group B — MIME edge cases (tests 4-6)
      HTML-only email, unicode preservation, empty body.

  Group C — Trust & sender parsing (test 7)
      Display-name stripping for trust classification.

  Group D — Attachments (tests 8-9)
      Single PDF, multiple mixed MIME types.

  Group E — Thread continuity (tests 10-11)
      In-Reply-To and References headers in outbound replies.

  Group F — ArtifactStore module (tests 12-13)
      Store/get/remove lifecycle, path-traversal guard.

  Group G — UidTracker module (test 14)
      Deduplication across multiple mark_seen calls.

  Group H — Subject cache (test 15)
      Per-thread subject isolation when two threads are open.
"""

from __future__ import annotations

import email as _stdlib_email
import email.policy as _stdlib_policy
from email.message import EmailMessage

import pytest

from glc.channels.catalogue.imap.adapter import Adapter
from glc.channels.catalogue.imap.artifacts import ArtifactStore
from glc.channels.catalogue.imap.uid_tracker import UidTracker
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.pairing import get_pairing_store
from tests.channels.mocks.imap_mock import OWNER_EMAIL, OWNER_ID, ImapMock

# ── Constants ─────────────────────────────────────────────────────────────────

BOT_EMAIL = "bot@example.com"
PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32   # minimal fake PNG header

# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def mock():
    return ImapMock()


@pytest.fixture
def pair_owner():
    store = get_pairing_store()
    store.force_pair_owner("imap", OWNER_ID, user_handle="owner")
    yield
    store.revoke("imap", OWNER_ID)


# ── Message builders ──────────────────────────────────────────────────────────


def _make_text_raw(
    *,
    from_addr: str = OWNER_EMAIL,
    subject: str = "Test",
    body: str = "hello",
    msg_id: str = "<test@example.com>",
) -> bytes:
    """Build a plain-text RFC 822 message."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = BOT_EMAIL
    msg["Subject"] = subject
    msg["Message-ID"] = msg_id
    msg["Date"] = "Tue, 01 Jul 2026 08:00:00 +0530"
    msg.set_content(body)
    return bytes(msg)


def _make_html_raw(*, from_addr: str = OWNER_EMAIL, body_text: str = "Hello") -> bytes:
    """Build an HTML-only RFC 822 message (no text/plain part)."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = BOT_EMAIL
    msg["Subject"] = "HTML only"
    msg["Message-ID"] = "<html@example.com>"
    msg["Date"] = "Tue, 01 Jul 2026 08:00:00 +0530"
    msg.set_content(f"<html><body><p>{body_text}</p></body></html>", subtype="html")
    return bytes(msg)


def _make_pdf_raw(*, from_addr: str = OWNER_EMAIL, body: str = "see attached") -> bytes:
    """Build a multipart/mixed message with one PDF attachment."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = BOT_EMAIL
    msg["Subject"] = "Report"
    msg["Message-ID"] = "<pdf@example.com>"
    msg["Date"] = "Tue, 01 Jul 2026 08:00:00 +0530"
    msg.set_content(body)
    msg.add_attachment(PDF_BYTES, maintype="application", subtype="pdf", filename="report.pdf")
    return bytes(msg)


def _make_multi_attachment_raw(*, from_addr: str = OWNER_EMAIL) -> bytes:
    """Build a multipart/mixed message with PDF + PNG attachments."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = BOT_EMAIL
    msg["Subject"] = "Multi"
    msg["Message-ID"] = "<multi@example.com>"
    msg["Date"] = "Tue, 01 Jul 2026 08:00:00 +0530"
    msg.set_content("two attachments below")
    msg.add_attachment(PDF_BYTES, maintype="application", subtype="pdf", filename="one.pdf")
    msg.add_attachment(PNG_BYTES, maintype="image", subtype="png", filename="two.png")
    return bytes(msg)


def _subject_of(raw: bytes | str) -> str:
    if isinstance(raw, str):
        raw = raw.encode()
    parsed = _stdlib_email.message_from_bytes(raw, policy=_stdlib_policy.default)
    return parsed.get("Subject") or ""


def _header_of(raw: bytes | str, header: str) -> str:
    if isinstance(raw, str):
        raw = raw.encode()
    parsed = _stdlib_email.message_from_bytes(raw, policy=_stdlib_policy.default)
    return parsed.get(header) or ""


# ── Group A: Input robustness ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_raw_returns_none(mock):
    """Empty raw bytes → on_message returns None."""
    adapter = Adapter(config={"mock": mock})
    result = await adapter.on_message({"uid": 1, "raw": b""})
    assert result is None


@pytest.mark.asyncio
async def test_missing_raw_key_returns_none(mock):
    """Dict without a 'raw' key → on_message returns None."""
    adapter = Adapter(config={"mock": mock})
    result = await adapter.on_message({"uid": 1})
    assert result is None


@pytest.mark.asyncio
async def test_corrupt_bytes_does_not_raise(mock):
    """Random binary garbage must not raise an exception.

    The stdlib email parser is extremely fault-tolerant. The adapter
    returns either None (if parse returns None) or a ChannelMessage
    with empty/None text — both are acceptable outcomes.
    """
    adapter = Adapter(config={"mock": mock})
    garbage = bytes(range(256)) * 8
    try:
        result = await adapter.on_message({"uid": 99, "raw": garbage})
    except Exception as exc:
        pytest.fail(f"Corrupt bytes raised unexpectedly: {exc!r}")
    # Result is None or a valid ChannelMessage — either is fine
    assert result is None or isinstance(result, ChannelMessage)


# ── Group B: MIME edge cases ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_html_only_email_returns_stripped_text(mock, pair_owner):
    """An HTML-only email must have its tags stripped before reaching the agent.

    This prevents HTML/JS from being injected into the agent's context window.
    """
    adapter = Adapter(config={"mock": mock})
    raw = _make_html_raw(from_addr=OWNER_EMAIL, body_text="Hello from HTML")
    msg = await adapter.on_message({"uid": 2, "raw": raw})

    assert msg is not None
    text = msg.text or ""
    assert "Hello from HTML" in text, f"Text content lost: {text!r}"
    assert "<" not in text, f"HTML tags must be stripped, got: {text!r}"


@pytest.mark.asyncio
async def test_unicode_body_preserved(mock, pair_owner):
    """UTF-8 body including emoji and CJK characters must survive the pipeline."""
    unicode_text = "こんにちは 🌏 Привет मुझे"
    adapter = Adapter(config={"mock": mock})
    raw = _make_text_raw(from_addr=OWNER_EMAIL, body=unicode_text)
    msg = await adapter.on_message({"uid": 3, "raw": raw})

    assert msg is not None
    assert unicode_text in (msg.text or ""), (
        f"Unicode not preserved. Got: {msg.text!r}"
    )


@pytest.mark.asyncio
async def test_empty_body_handled(mock, pair_owner):
    """An email with an empty body must not crash and must yield text='' or None."""
    adapter = Adapter(config={"mock": mock})
    raw = _make_text_raw(from_addr=OWNER_EMAIL, body="")
    msg = await adapter.on_message({"uid": 4, "raw": raw})

    assert msg is not None
    # The stdlib email parser may produce '\n' for an empty text/plain part.
    # Accept any blank or whitespace-only body as equivalent to empty.
    assert msg.text is None or (msg.text or "").strip() == ""


# ── Group C: Trust & sender parsing ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_display_name_stripped_for_trust(mock, pair_owner):
    """'Owner Name <owner@example.com>' → trust lookup uses bare email.

    If display names are not stripped, classify() sees a string like
    'Owner Name <owner@example.com>' and finds no pairing → untrusted.
    The adapter must strip to the bare address before the trust call.
    """
    adapter = Adapter(config={"mock": mock})
    display_name_addr = f"Owner Display Name <{OWNER_EMAIL}>"
    raw = _make_text_raw(from_addr=display_name_addr)
    msg = await adapter.on_message({"uid": 5, "raw": raw})

    assert msg is not None
    assert msg.channel_user_id == OWNER_EMAIL, (
        f"Display name not stripped. channel_user_id={msg.channel_user_id!r}"
    )
    assert "<" not in msg.channel_user_id
    assert msg.trust_level == "owner_paired", (
        f"Expected owner_paired, got {msg.trust_level!r}"
    )


# ── Group D: Attachments ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_attachment_extracted(mock, pair_owner):
    """A multipart/mixed message with a PDF must produce a typed Attachment.

    The Attachment must have:
      kind  = 'file'
      mime  = 'application/pdf'
      ref   = 'art:<hex>'   (not raw bytes inline in ChannelMessage.text)

    The text body must still be present — the PDF must not overwrite it.
    """
    adapter = Adapter(config={"mock": mock})
    raw = _make_pdf_raw(from_addr=OWNER_EMAIL, body="see attached")
    msg = await adapter.on_message({"uid": 6, "raw": raw})

    assert msg is not None
    assert "see attached" in (msg.text or ""), "Text body must survive alongside attachment"

    pdf = next(
        (a for a in msg.attachments if a.mime == "application/pdf"), None
    )
    assert pdf is not None, "No application/pdf attachment found"
    assert pdf.kind == "file"
    assert pdf.ref.startswith("art:"), (
        f"Attachment.ref must be an artifact handle (art:<hex>), got {pdf.ref!r}"
    )


@pytest.mark.asyncio
async def test_multiple_attachments(mock, pair_owner):
    """A message with PDF + PNG produces two separate Attachment objects."""
    adapter = Adapter(config={"mock": mock})
    raw = _make_multi_attachment_raw(from_addr=OWNER_EMAIL)
    msg = await adapter.on_message({"uid": 7, "raw": raw})

    assert msg is not None
    assert len(msg.attachments) == 2, (
        f"Expected 2 attachments, got {len(msg.attachments)}: {msg.attachments}"
    )
    mimes = {a.mime for a in msg.attachments}
    assert "application/pdf" in mimes, "PDF attachment missing"
    assert "image/png" in mimes, "PNG attachment missing"
    for att in msg.attachments:
        assert att.ref.startswith("art:"), f"ref must be art: handle, got {att.ref!r}"


# ── Group E: Thread continuity ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_reply_to_header_set(mock, pair_owner):
    """Outbound reply must contain In-Reply-To: <original Message-ID>.

    This is what causes MUAs (Outlook, Thunderbird, Apple Mail) to thread
    the reply under the original message.
    """
    adapter = Adapter(config={"mock": mock})
    original_msg_id = "<original-abc@example.com>"
    raw = _make_text_raw(from_addr=OWNER_EMAIL, msg_id=original_msg_id)
    msg = await adapter.on_message({"uid": 8, "raw": raw})
    assert msg is not None

    reply = ChannelReply(
        channel="imap",
        channel_user_id=OWNER_ID,
        text="reply text",
        thread_id=msg.thread_id,
    )
    await adapter.send(reply)

    assert len(mock.send_log) == 1
    in_reply_to = _header_of(mock.send_log[0]["raw"], "In-Reply-To")
    assert in_reply_to == original_msg_id, (
        f"Expected In-Reply-To: {original_msg_id!r}, got {in_reply_to!r}"
    )


@pytest.mark.asyncio
async def test_references_header_set(mock, pair_owner):
    """Outbound reply must contain a References header including the original Message-ID.

    References allows MUAs to reconstruct the full conversation thread
    even when a message's In-Reply-To is missing.
    """
    adapter = Adapter(config={"mock": mock})
    original_msg_id = "<original-def@example.com>"
    raw = _make_text_raw(from_addr=OWNER_EMAIL, msg_id=original_msg_id)
    msg = await adapter.on_message({"uid": 9, "raw": raw})
    assert msg is not None

    reply = ChannelReply(
        channel="imap",
        channel_user_id=OWNER_ID,
        text="reply text",
        thread_id=msg.thread_id,
    )
    await adapter.send(reply)

    assert len(mock.send_log) == 1
    references = _header_of(mock.send_log[0]["raw"], "References")
    assert references, "References header must be present"
    assert original_msg_id in references, (
        f"Original Message-ID {original_msg_id!r} not found in References: {references!r}"
    )


# ── Group F: ArtifactStore module ─────────────────────────────────────────────


def test_artifact_store_lifecycle(tmp_path):
    """store → get → remove round-trip with a real temp directory."""
    store = ArtifactStore(base_dir=tmp_path)
    data = b"hello artifact world"

    ref = store.store(data, mime="text/plain", filename="hello.txt")
    assert ref.startswith("art:"), f"ref must start with 'art:', got {ref!r}"

    retrieved = store.get(ref)
    assert retrieved == data, "get() must return the original bytes"

    store.remove(ref)
    assert store.get(ref) is None, "get() after remove() must return None"


def test_artifact_store_path_traversal(tmp_path):
    """Path-traversal attempts must raise ValueError before any file I/O."""
    store = ArtifactStore(base_dir=tmp_path)

    malicious_refs = [
        "art:../etc/passwd",        # classic traversal
        "art:../../secret",         # double traversal
        "art:AAAA/../../../etc",    # mid-path traversal
        "not-an-art-ref",           # missing art: prefix
        "art:",                     # empty key
        "art:UPPERCASE1234567",     # uppercase not allowed
    ]
    for ref in malicious_refs:
        with pytest.raises(ValueError, match="Invalid artifact"):
            store.get(ref)


# ── Group G: UidTracker module ────────────────────────────────────────────────


def test_uid_tracker_deduplication(tmp_path):
    """mark_seen() is idempotent; is_seen() reflects the correct state."""
    tracker = UidTracker(db_path=tmp_path / "uids.sqlite")
    mailbox = "INBOX"

    # Not seen initially
    assert not tracker.is_seen(mailbox, 42)

    # Mark seen
    tracker.mark_seen(mailbox, 42)
    assert tracker.is_seen(mailbox, 42)

    # Idempotent — marking again must not raise
    tracker.mark_seen(mailbox, 42)
    assert tracker.is_seen(mailbox, 42)

    # Different UID is independent
    assert not tracker.is_seen(mailbox, 99)

    # Different mailbox is independent
    assert not tracker.is_seen("Sent", 42)


# ── Group H: Subject cache ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subject_cache_per_thread(mock, pair_owner):
    """Two open threads must each receive the correct 'Re: <subject>' in replies.

    The subject cache is keyed by Message-ID (not sender), so two threads
    from the same user must not bleed into each other.
    """
    adapter = Adapter(config={"mock": mock})

    raw_a = _make_text_raw(
        from_addr=OWNER_EMAIL, subject="Thread Alpha", msg_id="<alpha@example.com>"
    )
    raw_b = _make_text_raw(
        from_addr=OWNER_EMAIL, subject="Thread Beta", msg_id="<beta@example.com>"
    )

    msg_a = await adapter.on_message({"uid": 10, "raw": raw_a})
    msg_b = await adapter.on_message({"uid": 11, "raw": raw_b})
    assert msg_a is not None and msg_b is not None

    # Send replies in reverse order to ensure no cross-contamination
    reply_b = ChannelReply(
        channel="imap", channel_user_id=OWNER_ID, text="reply B", thread_id=msg_b.thread_id
    )
    reply_a = ChannelReply(
        channel="imap", channel_user_id=OWNER_ID, text="reply A", thread_id=msg_a.thread_id
    )
    await adapter.send(reply_b)
    await adapter.send(reply_a)

    assert len(mock.send_log) == 2
    subj_b = _subject_of(mock.send_log[0]["raw"])
    subj_a = _subject_of(mock.send_log[1]["raw"])

    assert "Thread Beta" in subj_b, (
        f"Reply to Thread Beta got wrong subject: {subj_b!r}"
    )
    assert "Thread Alpha" in subj_a, (
        f"Reply to Thread Alpha got wrong subject: {subj_a!r}"
    )
