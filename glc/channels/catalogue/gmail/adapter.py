"""Gmail (Pub/Sub push) channel adapter.

Group 6 — modular structure (task specs: Tasks/README.md):
  Person 1 (Sai Teja):       GmailClient protocol, class skeleton, __init__, _get_client(), _LiveGmailClient
  Person 3 (Shrivastava):    _parse_pubsub_envelope()
  Person 4 (Harapanahalli):  _fetch_history()
  Person 5 (Nitha):          _fetch_message()
  Person 6 (Pankaj):         _extract_text_plain()
  Person 7 (Shrey):          on_message() orchestrator
  Person 8 (Shwetha):        _format_reply()
  Person 9 (Rajan):          send()
  Person 10 (Vishy):         _resolve_trust_level(), _check_allowlist(), _handle_rate_limit()
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import UTC, datetime
from email import policy as email_policy
from email.message import EmailMessage
from email.parser import BytesParser
from typing import Any, Literal, Protocol

from glc.channels.base import ChannelAdapter
from glc.channels.catalogue.gmail.artifacts import store as artifact_store
from glc.channels.catalogue.gmail.schemas import (
    GmailSendPayload,
    PubSubMessageData,
    PubSubPushNotification,
)
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import TrustLevel, classify

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Person 1 (Sai Teja): GmailClient protocol, skeleton, client wiring
# ──────────────────────────────────────────────────────────────────


class GmailClient(Protocol):
    """Protocol that both the mock and live client satisfy."""

    def history_list(self, start_history_id: int) -> dict: ...
    def messages_get(self, message_id: str) -> dict: ...
    async def send(self, payload: dict) -> dict: ...
    def pop_disconnect(self) -> bool: ...


class Adapter(ChannelAdapter):
    """Gmail channel adapter using Pub/Sub push notifications."""

    name = "gmail"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client: GmailClient | None = self.config.get("client") or self.config.get("mock")

    def _get_client(self) -> GmailClient:
        """Return the Gmail client (mock or live).

        In test/demo mode, uses config["mock"].
        In production, builds a real Gmail API service. OAuth credentials
        are loaded from the environment (no secrets in source):

          - GMAIL_OAUTH_CLIENT_ID     OAuth 2.0 client id
          - GMAIL_OAUTH_CLIENT_SECRET OAuth 2.0 client secret

        A previously authorized ``token.json`` (written by auth_setup) is
        used for the refresh token; the client id/secret needed to refresh
        it come from the environment so they are never committed.
        """
        if self._client is not None:
            return self._client

        from pathlib import Path

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_path = Path(__file__).parent / "token.json"
        scopes = ["https://www.googleapis.com/auth/gmail.modify"]

        client_id = os.getenv("GMAIL_OAUTH_CLIENT_ID")
        client_secret = os.getenv("GMAIL_OAUTH_CLIENT_SECRET")

        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        # Prefer env-provided client id/secret for the refresh exchange so
        # no long-lived OAuth client secret needs to live in token.json.
        if client_id and client_secret:
            creds = Credentials(
                token=creds.token,
                refresh_token=creds.refresh_token,
                token_uri=creds.token_uri or "https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
            )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        service = build("gmail", "v1", credentials=creds)
        self._client = _LiveGmailClient(service)
        return self._client

    # ──────────────────────────────────────────────────────────────────
    # Person 7 (Shrey): on_message() — main orchestrator
    # ──────────────────────────────────────────────────────────────────

    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        client = self._get_client()

        # Person 10 (Vishy): handle disconnect
        if client.pop_disconnect():
            return None  # type: ignore[return-value]

        # Person 3: parse the Pub/Sub envelope
        email_address, history_id = self._parse_pubsub_envelope(raw)

        # Person 4: fetch history to get new message IDs
        message_ids = self._fetch_history(history_id, client)
        if not message_ids:
            return None  # type: ignore[return-value]

        # Process the first message (one ChannelMessage per on_message call).
        # If multiple messages arrived simultaneously, the caller should
        # use on_messages() to get all of them, or call on_message per push.
        msg_id, thread_id = message_ids[0]

        # Person 5: fetch the full raw message
        raw_bytes = self._fetch_message(msg_id, client)
        if raw_bytes is None:
            return None  # type: ignore[return-value]

        # Parse headers only first — need From for trust check
        parser = BytesParser(policy=email_policy.default)
        email_msg = parser.parsebytes(raw_bytes)
        from_addr_raw = email_msg["From"] or ""
        from_addr = self._extract_email(from_addr_raw)

        # Person 10: resolve trust level — tags the message for the policy engine.
        # In normal mode, all messages are delivered with their trust tag.
        # In public channel mode, the adapter consults the allowlist before
        # processing strangers (mention_only_in_public default), so untrusted
        # senders are dropped at the adapter level to avoid flooding the agent.
        trust_level = self._resolve_trust_level(from_addr)

        if self.config.get("is_public_channel") and not self._check_allowlist(from_addr, trust_level):
            return None  # type: ignore[return-value]

        # Person 6: parse body and attachments
        text_body = self._extract_text_plain(email_msg)
        attachments = self._extract_attachments(email_msg)

        return ChannelMessage(
            channel="gmail",
            channel_user_id=from_addr,
            user_handle=from_addr,
            text=text_body,
            attachments=attachments,
            thread_id=thread_id,
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
        )

    async def on_messages(self, raw: Any) -> list[ChannelMessage]:
        """Process a Pub/Sub push that may contain multiple new messages.

        Unlike on_message() which returns only the first, this returns
        all messages from the history batch. Use when a single push
        notification corresponds to multiple simultaneous emails.
        """
        client = self._get_client()

        if client.pop_disconnect():
            return []

        email_address, history_id = self._parse_pubsub_envelope(raw)
        message_ids = self._fetch_history(history_id, client)
        if not message_ids:
            return []

        results: list[ChannelMessage] = []
        for msg_id, thread_id in message_ids:
            raw_bytes = self._fetch_message(msg_id, client)
            if raw_bytes is None:
                continue

            parser = BytesParser(policy=email_policy.default)
            email_msg = parser.parsebytes(raw_bytes)
            from_addr_raw = email_msg["From"] or ""
            from_addr = self._extract_email(from_addr_raw)

            trust_level = self._resolve_trust_level(from_addr)

            if self.config.get("is_public_channel") and not self._check_allowlist(from_addr, trust_level):
                continue

            text_body = self._extract_text_plain(email_msg)
            attachments = self._extract_attachments(email_msg)

            results.append(
                ChannelMessage(
                    channel="gmail",
                    channel_user_id=from_addr,
                    user_handle=from_addr,
                    text=text_body,
                    attachments=attachments,
                    thread_id=thread_id,
                    trust_level=trust_level,
                    arrived_at=datetime.now(UTC),
                )
            )

        return results

    # ──────────────────────────────────────────────────────────────────
    # Person 9 (Rajan): send() — Gmail send API integration
    # ──────────────────────────────────────────────────────────────────

    async def send(self, reply: ChannelReply) -> Any:
        # Person 8 (Shwetha): format the reply as MIME
        raw = self._format_reply(reply)

        # Build and validate the API request body
        send_payload = GmailSendPayload(
            raw=raw,
            threadId=reply.thread_id,
        )
        payload = send_payload.model_dump(exclude_none=True)

        # Call Gmail API
        client = self._get_client()
        result = await client.send(payload)

        # Person 10: propagate rate limits (do NOT swallow 429)
        self._handle_rate_limit(result)

        return result

    # ──────────────────────────────────────────────────────────────────
    # Person 3 (Shrivastava): Pub/Sub envelope parser
    # ──────────────────────────────────────────────────────────────────

    def _parse_pubsub_envelope(self, raw: dict[str, Any]) -> tuple[str, int]:
        """Decode the Pub/Sub push notification.

        The `message.data` field is base64-encoded JSON:
        {"emailAddress": "...", "historyId": N}

        Returns:
            (email_address, history_id)

        Raises:
            ValueError: if the envelope is malformed
        """
        try:
            notification = PubSubPushNotification(**raw)
            decoded_json = json.loads(base64.b64decode(notification.message.data))
            data = PubSubMessageData(**decoded_json)
        except (KeyError, json.JSONDecodeError, ValueError, TypeError) as e:
            raise ValueError(f"Malformed Pub/Sub envelope: {e}") from e
        return data.emailAddress, data.historyId

    # ──────────────────────────────────────────────────────────────────
    # Person 4 (Harapanahalli): Gmail History API client
    # ──────────────────────────────────────────────────────────────────

    def _fetch_history(self, history_id: int, client: GmailClient) -> list[tuple[str, str | None]]:
        """Call history.list to discover new message IDs.

        Returns:
            List of (message_id, thread_id) tuples
        """
        history = client.history_list(history_id)
        results: list[tuple[str, str | None]] = []
        for record in history.get("history", []):
            for added in record.get("messagesAdded", []):
                msg_info = added["message"]
                results.append((msg_info["id"], msg_info.get("threadId")))
        return results

    # ──────────────────────────────────────────────────────────────────
    # Person 5 (Nitha): Message fetcher
    # ──────────────────────────────────────────────────────────────────

    def _fetch_message(self, message_id: str, client: GmailClient) -> bytes | None:
        """Fetch a raw RFC 822 message by ID.

        Returns:
            Raw email bytes, or None if not found.
        """
        try:
            full_msg = client.messages_get(message_id)
        except KeyError:
            logger.warning("Message not found: %s", message_id)
            return None

        raw_b64 = full_msg.get("raw", "")
        if not raw_b64:
            return None

        padded = raw_b64 + "=" * (-len(raw_b64) % 4)
        return base64.urlsafe_b64decode(padded.encode())

    # ──────────────────────────────────────────────────────────────────
    # Person 6 (Pankaj): Email content parser
    # ──────────────────────────────────────────────────────────────────

    def _extract_text_plain(self, msg: Any) -> str:
        """Parse MIME message and extract the text/plain part only.

        Ignores text/html to avoid leaking inline scripts,
        tracking pixels, and quote-printable noise into the
        agent's context.
        """
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_content()
                    if isinstance(payload, bytes):
                        return payload.decode("utf-8", errors="replace")
                    return str(payload)
            return ""
        if msg.get_content_type() != "text/plain":
            return ""
        body = msg.get_content()
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)

    def _extract_attachments(self, msg: Any) -> list[Attachment]:
        """Extract non-text attachments from a MIME message.

        Walks all MIME parts. Anything that isn't text/plain or text/html
        and has a filename or a binary content type is treated as an
        attachment. Bytes are persisted to the artifact store.
        """
        attachments: list[Attachment] = []
        if not msg.is_multipart():
            return attachments

        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            filename = part.get_filename()

            if content_type in (
                "text/plain",
                "text/html",
                "multipart/mixed",
                "multipart/alternative",
                "multipart/related",
            ):
                continue

            if not filename and "attachment" not in disposition:
                continue

            try:
                payload = part.get_content()
            except Exception:
                continue

            if payload is None:
                continue

            if isinstance(payload, str):
                raw = payload.encode("utf-8")
            elif isinstance(payload, bytes):
                raw = payload
            else:
                continue

            ref = artifact_store(raw, filename=filename or "unnamed")
            kind = self._classify_attachment_kind(content_type)

            attachments.append(
                Attachment(
                    kind=kind,
                    ref=ref,
                    mime=content_type,
                    metadata={
                        "filename": filename or "unnamed",
                        "size_bytes": len(raw),
                    },
                )
            )

        return attachments

    def _classify_attachment_kind(
        self, mime_type: str
    ) -> Literal["image", "audio", "video", "file", "location"]:
        """Map MIME type to Attachment.kind literal."""
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("audio/"):
            return "audio"
        if mime_type.startswith("video/"):
            return "video"
        return "file"

    def _extract_email(self, addr: str) -> str:
        """Extract bare email from 'Display Name <email@x.com>' format."""
        if "<" in addr and ">" in addr:
            return addr.split("<")[1].split(">")[0]
        return addr.strip()

    # ──────────────────────────────────────────────────────────────────
    # Person 8 (Shwetha): Reply formatter
    # ──────────────────────────────────────────────────────────────────

    def _format_reply(self, reply: ChannelReply) -> str:
        """Format a ChannelReply as an RFC 2822 MIME message,
        base64url-encoded for the Gmail API.

        Args:
            reply: ChannelReply with .channel_user_id (recipient),
                   .text (body), .thread_id (for threading headers)

        Returns:
            Base64url-encoded MIME message string ready for
            Gmail API 'raw' field.
        """
        msg = EmailMessage()
        msg["To"] = reply.channel_user_id
        msg["From"] = os.getenv("GMAIL_BOT_ADDRESS", "me")
        msg["Subject"] = "Re: conversation"

        if reply.thread_id:
            msg["In-Reply-To"] = reply.thread_id
            msg["References"] = reply.thread_id

        msg.set_content(reply.text or "")

        raw_bytes = bytes(msg)
        return base64.urlsafe_b64encode(raw_bytes).decode().rstrip("=")

    # ──────────────────────────────────────────────────────────────────
    # Person 10 (Vishy): Trust level + error handling helpers
    # ──────────────────────────────────────────────────────────────────

    def _resolve_trust_level(self, sender_email: str) -> TrustLevel:
        """Determine trust level using the pairing store.

        Returns:
            'owner_paired' if sender is the channel owner
            'user_paired' if sender is a paired user
            'untrusted' for unknown senders
        """
        return classify("gmail", sender_email)

    def _check_allowlist(self, sender_email: str, trust_level: str) -> bool:
        """Check if a sender may be processed in a public channel.

        Consults the canonical per-channel allowlist
        (`glc.security.allowlists.allowed`), which reads `allowed_senders`
        and `mention_only_in_public` from channels.yaml. Owners and paired
        users always pass; unknown senders pass only if explicitly
        allowlisted.

        Returns:
            True if the message should be processed, False to drop.
        """
        owner_ids = [p.channel_user_id for p in get_pairing_store().owners(channel="gmail")]
        ok, _why = allowed(
            "gmail",
            sender_email,
            owner_ids=owner_ids,
            is_public_channel=True,
            was_mentioned=trust_level in ("owner_paired", "user_paired"),
        )
        return ok

    def _handle_rate_limit(self, response: Any) -> None:
        """Check if Gmail API returned 429 and log a warning.

        The 429 response is propagated to the caller as-is (not swallowed).
        Test 5 verifies the caller sees the 429 status in the return value.
        We do NOT catch or transform it — just log for observability.
        """
        if not isinstance(response, dict):
            return
        status = response.get("status") or (response.get("error") or {}).get("code")
        if status == 429:
            logger.warning("Gmail API rate limited (429): %s", response.get("error", {}).get("message", ""))


# ──────────────────────────────────────────────────────────────────
# Person 1 (Sai Teja): _LiveGmailClient — production GmailClient impl
# ──────────────────────────────────────────────────────────────────


class _LiveGmailClient:
    """Production Gmail API client satisfying the GmailClient protocol."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def history_list(self, start_history_id: int) -> dict:
        try:
            return (
                self._service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=str(start_history_id),
                    historyTypes=["messageAdded"],
                )
                .execute()
            )
        except Exception as e:
            logger.error("Gmail history.list failed: %s", e)
            return {"history": []}

    def messages_get(self, message_id: str) -> dict:
        return (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="raw",
            )
            .execute()
        )

    async def send(self, payload: dict) -> dict:
        return (
            self._service.users()
            .messages()
            .send(
                userId="me",
                body=payload,
            )
            .execute()
        )

    def pop_disconnect(self) -> bool:
        return False
