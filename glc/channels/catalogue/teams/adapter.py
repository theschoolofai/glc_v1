"""Microsoft Teams adapter (Bot Framework Connector).

Wire-format basis: the Bot Framework Activity protocol.
https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-activities
https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-create-messages

Two quirks drive most of this file's shape:

1. The `serviceUrl` Bot Framework hands you on an inbound Activity is
   per-conversation and dynamic. It is not part of the canonical
   ChannelReply envelope (the envelope is deliberately channel-agnostic),
   so we cache it -- keyed by sender -- every time on_message resolves
   one, and look it up again in send().
2. Adaptive Cards arrive as an `attachments[]` entry with
   contentType == application/vnd.microsoft.card.adaptive rather than as
   `text`. A user submitting a card is still expressing intent, so we
   lift the card's body text into ChannelMessage.text and keep the raw
   card under metadata["adaptive_card"] for anything downstream that
   wants the structured form (e.g. re-rendering a follow-up card).
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Literal

from glc.channels.base import ChannelAdapter
from glc.channels.catalogue.teams.schemas import ADAPTIVE_CARD_CONTENT_TYPE
from glc.channels.envelope import Attachment, ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

# Token cache for the Bot Framework client-credentials flow, keyed by
# TEAMS_APP_ID. Only touched by the (untested-against-live-API) real
# wire path in send() -- the mock path never needs a token.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _parse_timestamp(raw_ts: str | None) -> datetime:
    if not raw_ts:
        return datetime.now(UTC)
    # Bot Framework timestamps are RFC3339 with a trailing "Z"; Python's
    # fromisoformat wants an explicit offset.
    return datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))


def _extract_adaptive_card_text(card: dict[str, Any]) -> str | None:
    """Pull the first TextBlock's text out of an Adaptive Card body.

    Cards routinely nest TextBlocks inside Containers or ColumnSets, so
    this walks the body breadth-first rather than assuming body[0] is a
    TextBlock."""
    queue: list[Any] = list(card.get("body") or [])
    while queue:
        node = queue.pop(0)
        if not isinstance(node, dict):
            continue
        if node.get("type") == "TextBlock" and node.get("text"):
            return str(node["text"])
        nested = node.get("items") or node.get("columns") or []
        queue = queue + list(nested)
    return None


def _attachment_kind(content_type: str) -> Literal["image", "audio", "video", "file"]:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("audio/"):
        return "audio"
    if content_type.startswith("video/"):
        return "video"
    return "file"


def _was_mentioned(activity: dict[str, Any]) -> bool:
    """True if the bot itself (activity.recipient.id) appears in the
    Activity's `entities` as a mention. See:
    https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/channel-and-group-conversations#detect-mentions
    """
    bot_id = (activity.get("recipient") or {}).get("id")
    for entity in activity.get("entities") or []:
        if entity.get("type") == "mention":
            mentioned = entity.get("mentioned") or {}
            if mentioned.get("id") == bot_id:
                return True
    return False


async def _get_bot_framework_token() -> str:
    """Client-credentials exchange against the Bot Framework token
    endpoint. Azure stopped allowing new *multi-tenant* bot
    registrations after 2025-07-31, so this targets the single-tenant
    endpoint (requires TEAMS_TENANT_ID). Untested against the live API
    -- the CI suite only exercises the mock path. Verify against
    current Microsoft docs before relying on this in production."""
    import httpx

    app_id = os.environ["TEAMS_APP_ID"]
    app_password = os.environ["TEAMS_APP_PASSWORD"]
    tenant_id = os.environ["TEAMS_TENANT_ID"]
    cached = _TOKEN_CACHE.get(app_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": app_id,
                "client_secret": app_password,
                "scope": "https://api.botframework.com/.default",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    token = str(payload["access_token"])
    _TOKEN_CACHE[app_id] = (token, time.time() + float(payload.get("expires_in", 3600)))
    return token


class Adapter(ChannelAdapter):
    name = "teams"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._contexts: dict[str, dict[str, str]] = {}

    async def on_message(self, raw: Any) -> ChannelMessage | None:  # type: ignore[override]
        mock = self.config.get("mock")

        # A forced disconnect means the underlying HTTP/WS channel to
        # the Bot Framework Connector dropped mid-session. We must not
        # raise -- the gateway expects on_message to return cleanly so
        # it can reconnect and keep serving later events.
        if mock is not None and mock.pop_disconnect():
            return None

        activity: dict[str, Any] = raw

        # The Emulator (and real Connector) send non-message activity types
        # such as conversationUpdate, typing, and endOfConversation before
        # and alongside real messages. Only message activities carry user
        # intent; silently ignore everything else.
        if activity.get("type") != "message":
            return None

        from_obj = activity.get("from") or {}
        from_id = str(from_obj.get("id") or "")
        from_name = str(from_obj.get("name") or from_id)
        activity_id = str(activity["id"])
        service_url = str(activity.get("serviceUrl", ""))
        conversation = activity.get("conversation") or {}
        conversation_id = str(conversation.get("id", ""))
        tenant_id = conversation.get("tenantId") or (activity.get("channelData") or {}).get("tenant", {}).get(
            "id"
        )

        trust_level = classify(self.name, from_id)

        is_public_channel = bool(self.config.get("is_public_channel", False))
        if is_public_channel:
            owner_ids = [r.channel_user_id for r in get_pairing_store().owners(self.name)]
            ok, _reason = allowed(
                self.name,
                from_id,
                owner_ids=owner_ids,
                is_public_channel=True,
                was_mentioned=_was_mentioned(activity),
            )
            if not ok:
                # Silently drop -- a busy team channel must not trigger
                # the agent on every unrelated message that passes by.
                return None

        text: str | None = activity.get("text") or None
        metadata: dict[str, Any] = {
            "service_url": service_url,
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
        }

        attachments: list[Attachment] = []
        for attachment in activity.get("attachments") or []:
            content_type = attachment.get("contentType", "")
            if content_type == ADAPTIVE_CARD_CONTENT_TYPE:
                card = attachment.get("content") or {}
                metadata["adaptive_card"] = card
                card_text = _extract_adaptive_card_text(card)
                if card_text:
                    text = card_text
            elif attachment.get("contentUrl"):
                attachments.append(
                    Attachment(
                        kind=_attachment_kind(content_type),
                        ref=str(attachment["contentUrl"]),
                        mime=content_type or None,
                    )
                )

        # Remember where to address a reply for this sender -- send()
        # has no other way to learn serviceUrl/conversation_id, since
        # ChannelReply is deliberately channel-agnostic.
        self._contexts[from_id] = {
            "service_url": service_url,
            "conversation_id": conversation_id,
        }

        return ChannelMessage(
            channel=self.name,
            channel_user_id=from_id,
            user_handle=from_name,
            text=text,
            attachments=attachments,
            thread_id=activity_id,
            trust_level=trust_level,
            arrived_at=_parse_timestamp(activity.get("timestamp")),
            metadata=metadata,
        )

    async def send(self, reply: ChannelReply) -> Any:
        mock = self.config.get("mock")

        body: dict[str, Any] = {
            "type": "message",
            "text": reply.text or "",
        }
        if reply.thread_id:
            # Bot Framework threads a reply to a specific prior Activity
            # via replyToId, not a long-running thread abstraction.
            body["replyToId"] = reply.thread_id

        if mock is not None:
            return await mock.send(body)

        ctx = self._contexts.get(reply.channel_user_id, {})
        if not ctx.get("service_url") or not ctx.get("conversation_id"):
            raise RuntimeError(
                f"no cached conversation context for {reply.channel_user_id!r}; "
                "on_message must observe an inbound Activity from this user "
                "before send() can address a real reply"
            )

        import httpx

        token = await _get_bot_framework_token()
        url = (
            f"{ctx['service_url'].rstrip('/')}/v3/conversations/"
            f"{ctx['conversation_id']}/activities/{reply.thread_id or ''}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            result: Any = resp.json()
            return result
