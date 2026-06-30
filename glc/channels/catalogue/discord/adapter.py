"""Discord Gateway adapter.

Translates between Discord's wire format and the canonical channel
envelope in both directions:

  inbound  : MESSAGE_CREATE dispatch frame  -> ChannelMessage
  outbound : ChannelReply                   -> POST /channels/{id}/messages

Trust level is assigned on every inbound message via
glc.security.trust_level.classify(). In public channels the allowlist is
consulted before a stranger is processed. The Discord REST/gateway surface
is injected through config (the test mock, or a real client) so the same
code path runs under test and in production.

See docs/ADAPTER_GUIDE.md and glc/channels/catalogue/discord/README.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.catalogue.discord.schemas import DiscordCreateMessage, DiscordMessage
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.pairing import get_pairing_store
from glc.security.trust_level import classify

CHANNEL = "discord"


class Adapter(ChannelAdapter):
    name = "discord"

    @property
    def _api(self) -> Any:
        """The Discord transport — the test mock under `mock`, or a real
        gateway/REST client under `client`. Both expose async `send()` and
        `get_user()`."""
        return self.config.get("mock") or self.config.get("client")

    @property
    def _is_public(self) -> bool:
        return bool(self.config.get("is_public_channel", False))

    # ── inbound: Discord dispatch frame → ChannelMessage ──────────────────

    async def on_message(self, raw: Any) -> ChannelMessage | None:
        # A dropped gateway connection surfaces as a pending disconnect on the
        # transport. A live adapter resumes the session; for translation we
        # clear the flag and keep processing the delivered event instead of
        # raising up to the caller.
        api = self._api
        if api is not None and hasattr(api, "pop_disconnect"):
            api.pop_disconnect()

        payload = raw.get("d", raw) if isinstance(raw, dict) else raw
        msg = DiscordMessage.model_validate(payload)

        user_id = msg.author.id
        trust_level = classify(CHANNEL, user_id)

        # Resolve every mentioned user through the transport's directory so the
        # agent sees handles, not raw <@id> tokens.
        mentions: list[str] = []
        for m in msg.mentions:
            resolved = None
            if api is not None and hasattr(api, "get_user"):
                u = api.get_user(m.id)
                if u:
                    resolved = u.get("username") or u.get("global_name")
            mentions.append(resolved or m.username)

        bot_id = self.config.get("bot_user_id")
        was_mentioned = bool(bot_id) and any(m.id == str(bot_id) for m in msg.mentions)

        # Public channels: gate strangers through the allowlist before the
        # message reaches the agent. Owners always pass (subject to the
        # mention-only-in-public rule).
        if self._is_public:
            owner_ids = [r.channel_user_id for r in get_pairing_store().owners(CHANNEL)]
            ok, _reason = allowed(
                CHANNEL,
                user_id,
                owner_ids=owner_ids,
                is_public_channel=True,
                was_mentioned=was_mentioned,
            )
            if not ok:
                return None

        return ChannelMessage(
            channel=CHANNEL,
            channel_user_id=user_id,
            user_handle=msg.author.handle,
            text=msg.content,
            thread_id=msg.channel_id,
            trust_level=trust_level,
            arrived_at=_parse_ts(msg.timestamp),
            metadata={
                "message_id": msg.id,
                "guild_id": msg.guild_id,
                "mentions": mentions,
            },
        )

    # ── outbound: ChannelReply → Discord create-message ───────────────────

    async def send(self, reply: ChannelReply) -> Any:
        api = self._api
        if api is None:
            raise RuntimeError("discord adapter: no transport configured (config['mock'|'client'])")
        # tts defaults to False and is omitted from the wire body — Discord
        # text-to-speech is opt-in per channel.
        body = DiscordCreateMessage(content=reply.text or "")
        payload = body.model_dump(exclude={"tts"})
        return await api.send(payload)


def _parse_ts(ts: str | None) -> datetime:
    if ts:
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            pass
    return datetime.now(UTC)
