"""Matrix adapter (client-server API).

Inbound wire format is a ``/sync`` response carrying ``m.room.message``
timeline events. Outbound is the body of
``PUT /_matrix/client/v3/rooms/{roomId}/send/m.room.message/{txnId}`` —
``{"msgtype": "m.text", "body": "..."}``.

The adapter translates that wire format to and from the typed
``ChannelMessage`` / ``ChannelReply`` envelope and never lets the agent
runtime see a raw Matrix event. Trust level is decided in deterministic
code via :func:`glc.security.trust_level.classify`, not by the model.

See ``README.md`` and ``docs/ADAPTER_GUIDE.md`` for the workflow.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

_AttachmentKind = Literal["image", "audio", "video", "file", "location"]

# Matrix media-event msgtypes → envelope Attachment kinds.
_MEDIA_KINDS: dict[str, _AttachmentKind] = {
    "m.image": "image",
    "m.audio": "audio",
    "m.video": "video",
    "m.file": "file",
}


def _artifact_ref(data: bytes) -> str:
    """Persist-by-reference handle for downloaded media. Mirrors the
    ``art:<sha>`` convention the gateway resolves through its artifact
    store; the raw ``mxc://`` URI is never surfaced to the runtime."""
    sha = hashlib.sha256(data).hexdigest()[:16]
    return f"art:{sha}"


class Adapter(ChannelAdapter):
    name = "matrix"

    # -- inbound ---------------------------------------------------------

    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        mock = self.config.get("mock")

        # A dropped connection must not raise — the gateway keeps the
        # channel alive across reconnects. Consume the flag and continue
        # parsing the buffered event normally.
        if mock is not None and hasattr(mock, "pop_disconnect"):
            mock.pop_disconnect()

        event = self._first_timeline_event(raw)
        if event is None:
            return None

        content = event.get("content") or {}
        msgtype = content.get("msgtype", "")
        sender = event.get("sender", "")
        trust_level = classify(self.name, sender)

        # Public-channel posture: an unknown, un-mentioned sender is
        # silently dropped (allowlists default to mention_only_in_public).
        if self.config.get("is_public_channel"):
            owner_ids = [o.channel_user_id for o in get_pairing_store().owners(self.name)]
            ok, _reason = allowed(
                self.name,
                sender,
                owner_ids=owner_ids,
                is_public_channel=True,
                was_mentioned=False,
            )
            if not ok and trust_level == "untrusted":
                return None

        attachments, voice_ref = self._extract_media(content, mock)

        return ChannelMessage(
            channel=self.name,
            channel_user_id=sender,
            user_handle=self._display_name(event, sender),
            text=content.get("body") if msgtype == "m.text" else None,
            attachments=attachments,
            voice_audio_ref=voice_ref,
            thread_id=self._thread_id(content) or event.get("room_id"),
            trust_level=trust_level,
            arrived_at=self._arrived_at(event),
            metadata={
                "room_id": event.get("room_id"),
                "event_id": event.get("event_id"),
                "msgtype": msgtype,
            },
        )

    # -- outbound --------------------------------------------------------

    async def send(self, reply: ChannelReply) -> Any:
        body: dict[str, Any] = {
            "msgtype": "m.text",
            "body": reply.text or "",
        }
        # Media replies carry the artifact/URL handle alongside the text
        # body so the gateway can attach it on dispatch.
        if reply.voice_audio_ref:
            body["msgtype"] = "m.audio"
            body["url"] = reply.voice_audio_ref
        elif reply.attachments:
            first = reply.attachments[0]
            body["msgtype"] = f"m.{first.kind}"
            body["url"] = first.ref

        mock = self.config.get("mock")
        if mock is not None:
            return await mock.send(body)
        # Real client path would PUT to /rooms/{roomId}/send/... here.
        return body

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _first_timeline_event(raw: Any) -> dict[str, Any] | None:
        """Pull the first ``m.room.message`` out of a ``/sync`` response.
        Accepts either a full sync response or a bare event dict."""
        if not isinstance(raw, dict):
            return None
        if raw.get("type") == "m.room.message":
            return raw
        joined = ((raw.get("rooms") or {}).get("join")) or {}
        for room_id, room in joined.items():
            for ev in (room.get("timeline") or {}).get("events", []):
                if ev.get("type") == "m.room.message":
                    ev.setdefault("room_id", room_id)
                    return ev
        return None

    def _extract_media(
        self, content: dict[str, Any], mock: Any
    ) -> tuple[list[Attachment], str | None]:
        kind = _MEDIA_KINDS.get(content.get("msgtype", ""))
        if kind is None:
            return [], None
        mxc = content.get("url")
        if not mxc:
            return [], None

        ref = mxc
        if mock is not None and hasattr(mock, "download_media"):
            # Resolve mxc:// → bytes and persist by reference. The agent
            # runtime gets an art: handle, never a raw mxc URI.
            data = mock.download_media(mxc)
            ref = _artifact_ref(data)

        mime = (content.get("info") or {}).get("mimetype")
        att = Attachment(kind=kind, ref=ref, mime=mime, metadata={"mxc": mxc})
        if kind == "audio":
            return [att], ref
        return [att], None

    @staticmethod
    def _thread_id(content: dict[str, Any]) -> str | None:
        rel = content.get("m.relates_to") or {}
        if rel.get("rel_type") == "m.thread":
            return rel.get("event_id")
        return None

    @staticmethod
    def _display_name(event: dict[str, Any], sender: str) -> str:
        # `@owner:matrix.org` → `owner` when no displayname is present.
        name = (event.get("content") or {}).get("displayname")
        if name:
            return str(name)
        if sender.startswith("@") and ":" in sender:
            return sender[1:].split(":", 1)[0]
        return sender

    @staticmethod
    def _arrived_at(event: dict[str, Any]) -> datetime:
        ts = event.get("origin_server_ts")
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=UTC)
        return datetime.now(tz=UTC)
