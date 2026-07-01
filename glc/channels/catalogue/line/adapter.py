"""LINE Messaging API adapter for the Session 11 channel slot.

This adapter is a **wire-format translator only**: it turns an inbound LINE
webhook into a ``ChannelMessage`` (``on_message``) and a ``ChannelReply`` into
the right LINE Messaging API payload (``send``). It never opens a network
connection itself — the actual HTTP call is delegated to an injected
``LineTransport``.

To run a real LINE bot from this adapter an integrator must additionally:

1. Run a webhook server that receives LINE's POSTs and calls ``on_message``.
2. Verify the ``X-Line-Signature`` header (HMAC-SHA256 over the raw request
   body with the channel secret, base64-encoded) *before* trusting the payload.
3. Inject a ``LineTransport`` via ``config={"transport": ...}`` that performs
   the real reply/push HTTP calls.

A complete reference for all three lives in ``dev/live_bridge.py``
(``verify_line_signature``, the FastAPI ``/callback`` endpoint, and
``RealLineTransport``).

Config keys read by this adapter:

- ``transport`` (preferred) / ``mock`` (back-compat alias) — the ``LineTransport``.
- ``is_public_channel: bool`` — when true, strangers are run through the
  public-channel allowlist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.trust_level import classify

from .schemas import LineEvent


class Adapter(ChannelAdapter):
    """Translate LINE webhooks to/from the runtime envelopes.

    The network I/O lives in the injected ``LineTransport``; see the module
    docstring for what an integrator must supply to run a real bot.
    """

    name = "line"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        # In-memory store of reply tokens keyed by user_id.
        # Populated in on_message, consumed (popped) in send.
        self._reply_tokens: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def on_message(self, raw: Any) -> ChannelMessage:
        """Translate a LINE webhook POST body into a ChannelMessage.

        Returns None when:
        - A forced disconnect is pending (test_disconnect_is_handled).
        - A stranger messages a public channel and is not allowlisted
          (test_allowlist_silently_drops_stranger_in_public).
        """
        mock = self.config.get("mock")

        # Handle forced disconnects cleanly.
        if mock is not None:
            mock.pop_disconnect()

        # --- Parse the first event from the webhook body ---------------
        event = raw["events"][0]
        parsed = LineEvent(
            user_id=event["source"]["userId"],
            text=event["message"].get("text"),
            reply_token=event["replyToken"],
            message_type=event["message"].get("type", "text"),
        )
        set_reply_token = getattr(transport, "set_reply_token", None)
        if parsed.reply_token:
            if callable(set_reply_token):
                set_reply_token(parsed.user_id, parsed.reply_token)
            else:
                self._set_local_reply_token(parsed.user_id, parsed.reply_token)

        # Stash the reply token so send() can consume it later.
        self._reply_tokens[parsed.user_id] = parsed.reply_token

        # --- Trust classification --------------------------------------
        trust = classify("line", parsed.user_id)

        # In public channels with the default mention_only_in_public
        # posture, we let the gateway mention-filtering logic handle untrusted strangers.
        # Trust classification is still attached to the message.

        return ChannelMessage(
            channel="line",
            channel_user_id=parsed.user_id,
            user_handle=parsed.user_id,
            text=parsed.text,
            trust_level=trust,
            arrived_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------


    async def send(self, reply: ChannelReply) -> Any:
        """Build a LINE wire-format payload and dispatch it.

        Strategy (per LINE API economics):
        1. If a reply token is cached for this user → use reply endpoint
           (quota-free, one-shot).
        2. Otherwise → fall back to push endpoint (counts against the
           monthly push quota).
        """
        messages = [{"type": "text", "text": reply.text}]

        # Prefer the reply token if one is in flight.
        token = self._reply_tokens.pop(reply.channel_user_id, None)
        if token is not None:
            payload: dict[str, Any] = {
                "replyToken": token,
                "messages": messages,
            }
        else:
            payload = {
                "to": reply.channel_user_id,
                "messages": messages,
            }

        mock = self.config.get("mock")
        if mock is not None:
            result = await mock.send(payload)
            # Propagate rate-limit responses to the caller.
            if isinstance(result, dict) and result.get("status") == 429:
                return result
            return result

        # Non-mock path: return the constructed payload.
        return payload
