"""Real Discord API WebSocket & REST Bridge for GLC v1.

Runs an external client process that connects to Discord's Gateway (WebSocket)
and routes messages to/from the local GLC Gateway server over a WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import websockets
from dotenv import load_dotenv

from glc.channels.catalogue.discord.adapter import Adapter
from glc.channels.envelope import ChannelReply
from glc.config import get_or_create_install_token

# Load environment variables from .env at repository root
load_dotenv(Path(__file__).parent.parent.parent.parent.parent / ".env")


class RealDiscordClient:
    """Client transport wrapper passed to the adapter under config['client'].

    Handles outbound REST requests and keeps track of the active channel context.
    """

    def __init__(self, token: str) -> None:
        self.token = token
        self.current_channel_id: str | None = None
        self.headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/jssunil/glc_v1_g2_discord, 0.1.0)",
        }

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatches the outbound message content via POST request to Discord REST API."""
        if not self.current_channel_id:
            raise ValueError("No active Discord channel ID set in client context.")

        url = f"https://discord.com/api/v10/channels/{self.current_channel_id}/messages"

        async with httpx.AsyncClient() as client:
            print(f"[bridge] sending POST to Discord channel {self.current_channel_id}: {payload}")
            response = await client.post(url, json=payload, headers=self.headers)

            # Rate limit handling
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 1.0)
                print(f"[bridge] Discord rate limit hit. Retry after {retry_after}s")
                return {
                    "status": 429,
                    "message": "You are being rate limited.",
                    "retry_after": retry_after,
                    "global": False,
                    "code": 0,
                }

            response.raise_for_status()
            return response.json()

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch user profile to resolve mentions.

        Uses synchronous request or blocks since the adapter resolves mentions synchronously.
        """
        url = f"https://discord.com/api/v10/users/{user_id}"
        try:
            with httpx.Client() as client:
                response = client.get(url, headers=self.headers)
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            print(f"[bridge] failed to resolve user {user_id}: {e!r}")
        return None


async def heartbeat_loop(ws: Any, interval_ms: int):
    """Sends heartbeats to Discord Gateway to keep the connection alive."""
    interval = interval_ms / 1000.0
    print(f"[bridge] heartbeat loop started (every {interval}s)")
    try:
        while True:
            await asyncio.sleep(interval)
            # op: 1 is Heartbeat
            await ws.send(json.dumps({"op": 1, "d": None}))
    except asyncio.CancelledError:
        pass


async def run_bridge():
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    if not bot_token:
        print("ERROR: DISCORD_BOT_TOKEN environment variable is not set.", file=sys.stderr)
        print("Please set it in your environment or .env file before running.", file=sys.stderr)
        return

    # 1. Retrieve the GLC local install token to authorize with the GLC gateway
    install_token = get_or_create_install_token()
    glc_port = os.environ.get("GLC_PORT", "8111")
    glc_ws_url = f"ws://localhost:{glc_port}/v1/channels/discord?token={install_token}"

    # 2. Instantiate client and adapter
    client = RealDiscordClient(token=bot_token)
    adapter = Adapter(config={"client": client})

    print("[bridge] connecting to local GLC gateway...")
    async with websockets.connect(glc_ws_url) as glc_ws:
        print("[bridge] connected to GLC gateway. Connecting to Discord WebSocket gateway...")

        # 3. Connect to Discord Gateway
        discord_ws_url = "wss://gateway.discord.gg/?v=10&encoding=json"
        async with websockets.connect(discord_ws_url) as discord_ws:
            # 4. Handle initial Discord handshake (Hello payload)
            hello_msg = await discord_ws.recv()
            hello_data = json.loads(hello_msg)
            heartbeat_interval = hello_data["d"]["heartbeat_interval"]

            # Start background heartbeat task
            heartbeat_task = asyncio.create_task(heartbeat_loop(discord_ws, heartbeat_interval))

            # 5. Identify bot to Discord
            # Intents: GUILDS (1 << 0) + GUILD_MESSAGES (1 << 9) + MESSAGE_CONTENT (1 << 15) + DIRECT_MESSAGES (1 << 12) = 37377
            identify_payload = {
                "op": 2,
                "d": {
                    "token": bot_token,
                    "intents": 37377,
                    "properties": {"os": sys.platform, "browser": "glc_bridge", "device": "glc_bridge"},
                },
            }
            await discord_ws.send(json.dumps(identify_payload))
            print("[bridge] identified with Discord gateway. Listening for events...")

            # 6. Main event loop: Bridge messages between Discord and GLC
            async def handle_inbound():
                async for raw_event in discord_ws:
                    event = json.loads(raw_event)
                    if event.get("t") == "MESSAGE_CREATE":
                        # Ignore messages sent by the bot itself
                        author = event["d"].get("author", {})
                        if author.get("bot"):
                            continue

                        print(f"[bridge] received Discord message: {event['d'].get('content')}")

                        # Translate the Discord JSON dispatch into a canonical ChannelMessage
                        msg = await adapter.on_message(event)
                        if msg:
                            # Forward it over WebSocket to the GLC Gateway
                            await glc_ws.send(msg.model_dump_json())
                            print("[bridge] forwarded message to GLC gateway")

            async def handle_outbound():
                async for raw_reply in glc_ws:
                    reply_payload = json.loads(raw_reply)
                    if "error" in reply_payload:
                        print(f"[bridge] GLC error: {reply_payload['error']}")
                        continue

                    reply = ChannelReply.model_validate(reply_payload)
                    print(f"[bridge] received reply from GLC: {reply.text}")

                    # Set the active channel ID in the client context
                    client.current_channel_id = reply.thread_id

                    # Dispatch to Discord
                    await adapter.send(reply)

            try:
                await asyncio.gather(handle_inbound(), handle_outbound())
            finally:
                heartbeat_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(run_bridge())
    except KeyboardInterrupt:
        print("\n[bridge] shut down.")
