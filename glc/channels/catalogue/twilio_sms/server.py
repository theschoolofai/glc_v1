"""Live server for the Twilio SMS/MMS adapter — full WebSocket demo.

Flow (see README.md's "Live Demo" section):
    Phone --SMS--> Twilio --POST--> this receiver --on_message--> ChannelMessage
      --WS--> GLC gateway (:8111) --echo--> ChannelReply --adapter.send--> Twilio --> Phone

Run:
    cd glc_v1
    # terminal A:  uv run glc serve                       (the gateway, :8111)
    # terminal B:  ngrok http 8200                        (public tunnel)
    # terminal C:
    GLC_PUBLIC_BASE=https://<id>.ngrok.io \
      uv run python -m glc.channels.catalogue.twilio_sms.server

Env:
    TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER   (adapter + signing)
    TWILIO_OWNER_NUMBER      your mobile, paired as owner (owner_paired)
    GLC_PUBLIC_BASE          the ngrok https URL (serves /artifacts for outbound MMS)
    GLC_TWILIO_WEBHOOK_PORT  receiver port (default 8200)
    GLC_GATEWAY_HOST/PORT    gateway location (default localhost:8111)
    GLC_TWILIO_SKIP_SIG=1    dev-only: skip signature verification
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from glc.channels.envelope import ChannelMessage
from glc.security.pairing import get_pairing_store

from .adapter import Adapter
from .webhook import build_app, gateway_roundtrip

load_dotenv(Path(__file__).resolve().parents[5] / ".env")  # matches glc/main.py's convention

# ─── ANSI colors ─────────────────────────────────────────────────────────────
DIM = "\033[38;5;250m"
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[38;5;114m"
CYAN = "\033[38;5;81m"
YELLOW = "\033[38;5;221m"
RED = "\033[38;5;203m"
WHITE = "\033[97m"


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _rule(char: str = "━", n: int = 66) -> str:
    return f"{CYAN}{char * n}{RESET}"


def _field(label: str, value: str, color: str = "") -> None:
    print(f"     {DIM}{label:14s}{RESET} {color or WHITE}{value}{RESET}")


def _trust_color(trust: str) -> str:
    return GREEN if trust == "owner_paired" else YELLOW if trust == "user_paired" else RED


def _config() -> dict[str, Any]:
    return {
        "account_sid": os.environ.get("TWILIO_ACCOUNT_SID", ""),
        "auth_token": os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "phone_number": os.environ.get("TWILIO_PHONE_NUMBER", ""),
        "owner_number": os.environ.get("TWILIO_OWNER_NUMBER", ""),
        "public_base": os.environ.get("GLC_PUBLIC_BASE", "").rstrip("/"),
        "port": int(os.environ.get("GLC_TWILIO_WEBHOOK_PORT", "8200")),
        "gw_host": os.environ.get("GLC_GATEWAY_HOST", "localhost"),
        "gw_port": int(os.environ.get("GLC_GATEWAY_PORT", "8111")),
    }


def _make_handle_message(adapter: Adapter, cfg: dict[str, Any]):
    """Build the async callback the receiver runs for each inbound envelope:
    print it, round-trip through the gateway WS, then send the reply."""

    async def handle_message(msg: ChannelMessage) -> None:
        print(f"\n{_rule()}")
        print(f"  {BOLD}>> INCOMING {msg.channel.upper()}{RESET}  {DIM}{ts()}{RESET}")
        print(_rule())
        tc = _trust_color(msg.trust_level)
        _field("from", msg.channel_user_id)
        _field("trust", msg.trust_level, tc)
        _field("text", (msg.text or "(empty)"))
        if msg.attachments:
            for a in msg.attachments:
                _field("attachment", f"kind={a.kind} mime={a.mime} ref={a.ref}", CYAN)
        if msg.metadata.get("sms_keyword"):
            _field("keyword", msg.metadata["sms_keyword"], YELLOW)

        # ── Bridge to the GLC gateway over a real WebSocket ──
        print(
            f"\n  {BOLD}-> WS /v1/channels/{msg.channel}{RESET} {DIM}ws://{cfg['gw_host']}:{cfg['gw_port']}{RESET}"
        )
        try:
            reply = await gateway_roundtrip(msg, host=cfg["gw_host"], port=cfg["gw_port"])
        except Exception as e:
            print(f"  {RED}gateway unreachable: {e!r}{RESET}")
            print(f"  {DIM}(is `uv run glc serve` running on {cfg['gw_host']}:{cfg['gw_port']}?){RESET}")
            return

        # Gateway dropped or rate-limited the message.
        if isinstance(reply, dict):
            _field("gateway", str(reply), RED)
            return

        _field("echo", reply.text or "", GREEN)

        # ── Send the reply back to the phone via Twilio REST ──
        print(f"\n  {BOLD}-> adapter.send(ChannelReply){RESET}")
        result = await adapter.send(reply)
        if isinstance(result, dict) and (result.get("status") == 429 or result.get("code") == 20429):
            _field("send", f"rate-limited {result.get('code')}", RED)
        else:
            _field("send", str(result.get("sid") or result.get("status") or result), GREEN)
        print(f"{_rule()}\n")

    return handle_message


def main() -> None:
    import uvicorn

    cfg = _config()
    print(_rule())
    print(f"  {BOLD}{WHITE}GLC v1 — Twilio SMS/MMS Adapter{RESET}  {DIM}Live WebSocket demo{RESET}")
    print(_rule())

    # ── Pair the owner so inbound is classified owner_paired ──
    if cfg["owner_number"]:
        get_pairing_store().force_pair_owner("twilio_sms", cfg["owner_number"], user_handle="owner")
        _field("owner", cfg["owner_number"], GREEN)
        _field("trust", "owner_paired", GREEN)
    else:
        _field("owner", "TWILIO_OWNER_NUMBER unset — senders will be untrusted", YELLOW)

    _field("bot number", cfg["phone_number"] or "(TWILIO_PHONE_NUMBER unset)")
    _field("gateway", f"ws://{cfg['gw_host']}:{cfg['gw_port']}/v1/channels/twilio_sms", CYAN)

    # Outbound MMS: let the adapter turn art:<sha> refs into public MediaUrls
    # served by this process's /artifacts route.
    if cfg["public_base"]:
        os.environ["GLC_ARTIFACT_PUBLIC_BASE"] = f"{cfg['public_base']}/artifacts"
        _field("public base", cfg["public_base"], CYAN)
        _field("webhook url", f"{cfg['public_base']}/webhooks/twilio_sms", CYAN)
    else:
        _field("public base", "GLC_PUBLIC_BASE unset — set it to your ngrok https URL", YELLOW)

    if os.environ.get("GLC_TWILIO_SKIP_SIG"):
        _field("signature", "VERIFICATION DISABLED (GLC_TWILIO_SKIP_SIG)", YELLOW)

    adapter = Adapter(config={"phone_number": cfg["phone_number"]})
    app = build_app(adapter, _make_handle_message(adapter, cfg))

    print(
        f"\n  {GREEN}Listening{RESET} on {WHITE}0.0.0.0:{cfg['port']}{RESET}  "
        f"{DIM}POST {'{base}'}/webhooks/twilio_sms  ·  Ctrl+C to stop{RESET}\n"
    )
    uvicorn.run(app, host="0.0.0.0", port=cfg["port"], log_level="warning")


if __name__ == "__main__":
    main()
