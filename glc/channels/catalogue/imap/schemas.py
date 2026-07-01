"""Channel-specific Pydantic types for the IMAP/SMTP adapter.

Canonical ChannelMessage / ChannelReply envelopes live in
glc.channels.envelope; these types cover the wire-level details
specific to IMAP/SMTP: connection config, raw IMAP fetch envelopes,
parsed email structure, and SMTP outbound payloads.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImapConfig(BaseModel):
    """Full IMAP/SMTP connection configuration.

    Defaults target Zoho Mail (India region). Override via environment
    variables — see .env.example for the full list.
    """

    # IMAP (inbound)
    imap_host: str = Field(default="imap.zoho.in", description="IMAP server hostname")
    imap_port: int = Field(default=993, description="IMAP port — 993 = SSL/TLS (default)")
    imap_user: str = Field(default="", description="IMAP login username (email address)")
    imap_password: str = Field(default="", description="IMAP App Password (never the login password)")
    mailbox: str = Field(default="INBOX", description="Mailbox / folder to watch")

    # SMTP (outbound)
    smtp_host: str = Field(default="smtp.zoho.in", description="SMTP server hostname")
    smtp_port: int = Field(default=587, description="SMTP port — 587 = STARTTLS (default)")
    smtp_user: str = Field(default="", description="SMTP login username")
    smtp_password: str = Field(default="", description="SMTP App Password")

    # Bot identity
    bot_from: str = Field(default="", description="From address for outbound emails")
    default_subject: str = Field(default="Message from bot", description="Subject for agent-initiated emails")

    # Channel policy
    is_public_channel: bool = Field(default=False, description="Drop untrusted senders when True")

    # Storage paths (empty = use defaults under ~/.glc/)
    uid_db_path: str = Field(
        default="", description="SQLite path for UID tracker; '' → ~/.glc/imap_uids.sqlite"
    )
    artifacts_dir: str = Field(default="", description="Artifact store directory; '' → ~/.glc/artifacts")


class RawEnvelope(BaseModel):
    """Wire shape from an IMAP FETCH command.

    uid  — the IMAP UID of the message (integer, unique per mailbox).
    raw  — the full RFC 822 message bytes returned by FETCH UID RFC822.
    """

    uid: int
    raw: bytes


class ParsedEmail(BaseModel):
    """Structured result of parsing a raw RFC 822 message.

    Produced by mime_parser.parse(); consumed by the adapter to build
    a ChannelMessage. The html field is retained for audit purposes
    but is NOT forwarded to the agent (prevents HTML/JS injection).
    """

    uid: int | None = None
    message_id: str | None = None  # Message-ID header (thread anchor)
    sender: str = ""  # Bare email address (display name stripped)
    subject: str = ""
    text: str = ""  # text/plain content (agent-visible)
    html: str = ""  # text/html content (audit only)
    attachments: list[dict] = Field(  # [{mime, filename, data: bytes}]
        default_factory=list
    )
    references: str | None = None  # References header (thread chain)
    in_reply_to: str | None = None  # In-Reply-To header


class OutboundPayload(BaseModel):
    """Wire shape handed to the SMTP transport layer.

    Matches the shape expected by ImapMock.send() in tests:
        {"from": str, "to": str, "raw": bytes}
    """

    from_addr: str
    to: str
    raw: bytes
