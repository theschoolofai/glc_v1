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
from typing import Any, Literal, Protocol, overload

from glc.channels.base import ChannelAdapter
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.security.allowlists import allowed
from glc.security.trust_level import classify


class LineTransport(Protocol):
    """The transport an integrator must inject so the adapter can reach LINE.

    Inject an object satisfying this Protocol via ``config={"transport": ...}``
    (the key ``"mock"`` is accepted as a back-compat alias).

    Required methods — the adapter calls these unconditionally:

    - ``send(payload)`` — POST the LINE Messaging API payload (a reply or push
      body) and return the API's JSON response, or a ``{"status": 429, ...}``
      dict when rate limited.
    - ``consume_reply_token(user_id)`` — pop a still-valid reply token for the
      user, or return ``None`` so the adapter falls back to a push message.

    Recommended optional extensions — the adapter calls these defensively via
    ``getattr`` and degrades gracefully if they are absent. They are kept out
    of the Protocol because Protocol members are mandatory:

    - ``set_reply_token(user_id, token, ttl_s=60.0) -> None`` — store an inbound
      reply token in a TTL cache. Omit it and reply tokens are never stored, so
      every outbound becomes a quota-costing push.
    - ``pop_disconnect() -> bool`` — report whether a disconnect was signalled.
      Omit it and disconnect handling is simply skipped.

    ``RealLineTransport`` in ``dev/live_bridge.py`` is a complete reference
    implementation (real ``httpx`` calls to ``api.line.me`` with a Bearer token,
    plus the reply-token TTL store).
    """

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def consume_reply_token(self, user_id: str) -> str | None: ...


class Adapter(ChannelAdapter):
    """Translate LINE webhooks to/from the runtime envelopes.

    The network I/O lives in the injected ``LineTransport``; see the module
    docstring for what an integrator must supply to run a real bot.
    """

    name = "line"

    @overload
    def _transport(self, *, required: Literal[True]) -> LineTransport: ...

    @overload
    def _transport(self, *, required: Literal[False]) -> LineTransport | None: ...

    def _transport(self, *, required: bool) -> LineTransport | None:
        """Resolve the injected transport (preferred ``transport`` key, falling
        back to the ``mock`` alias). Raise a clear error when ``required`` and
        none was supplied, instead of a bare ``KeyError``."""
        transport = self.config.get("transport")
        if transport is None:
            transport = self.config.get("mock")
        if transport is None and required:
            raise RuntimeError(
                "line adapter has no transport: inject one via "
                "config={'transport': ...} satisfying LineTransport (this module). "
                "See RealLineTransport in dev/live_bridge.py for a reference."
            )
        return transport

    async def on_message(self, raw: Any) -> ChannelMessage:
        transport = self._transport(required=False)
        pop_disconnect = getattr(transport, "pop_disconnect", None)
        if callable(pop_disconnect):
            pop_disconnect()

        event = raw["events"][0]
        source = event["source"]
        message = event["message"]
        user_id = source["userId"]
        reply_token = event.get("replyToken")
        set_reply_token = getattr(transport, "set_reply_token", None)
        if reply_token and callable(set_reply_token):
            set_reply_token(user_id, reply_token)

        trust_level = classify(self.name, user_id)
        if self.config.get("is_public_channel") and trust_level == "untrusted":
            allowed(self.name, user_id, is_public_channel=True)

        return ChannelMessage(
            channel=self.name,
            channel_user_id=user_id,
            user_handle=user_id,
            text=message.get("text"),
            trust_level=trust_level,
            arrived_at=datetime.now(UTC),
        )

    async def send(self, reply: ChannelReply) -> Any:
        transport = self._transport(required=True)
        message = {"type": "text", "text": reply.text or ""}
        reply_token = transport.consume_reply_token(reply.channel_user_id)

        payload: dict[str, Any]
        if reply_token:
            payload = {"replyToken": reply_token, "messages": [message]}
        else:
            payload = {"to": reply.channel_user_id, "messages": [message]}

        return await transport.send(payload)
