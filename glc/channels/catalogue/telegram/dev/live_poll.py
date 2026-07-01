"""Helper script to test the Telegram adapter live with long-polling.

Requires:
  - TELEGRAM_BOT_TOKEN env variable.
  - A running GLC gateway (uv run glc serve) on port 8111.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import httpx

# Load environment
from dotenv import load_dotenv

from glc.channels.catalogue.telegram.adapter import Adapter
from glc.channels.envelope import ChannelReply
from glc.config import get_or_create_install_token
from glc.security.pairing import get_pairing_store

load_dotenv()


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        print("Please set it in your environment or a .env file.")
        sys.exit(1)

    print("Telegram Live Polling Bridge Starting...")

    # 1. Ask for owner chat ID or read it from env to pair automatically
    owner_id = os.getenv("TELEGRAM_OWNER_ID")
    store = get_pairing_store()

    if owner_id:
        store.force_pair_owner("telegram", owner_id, user_handle="owner")
        print(f"Paired owner Telegram ID (from env): {owner_id}")
    else:
        print("\n[live_poll] No TELEGRAM_OWNER_ID set. Will auto-pair the first user who messages the bot!")

    # 2. Get Gateway connection details
    gateway_port = int(os.getenv("GLC_PORT", "8111"))
    install_token = get_or_create_install_token()

    # Instantiate the adapter
    adapter = Adapter()

    # WebSocket URL
    ws_url = f"ws://localhost:{gateway_port}/v1/channels/telegram?token={install_token}"

    print(f"Connecting to GLC Gateway WebSocket at: ws://localhost:{gateway_port}/v1/channels/telegram")

    try:
        import websockets
    except ImportError:
        print("Installing websockets library...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
        import websockets

    async with websockets.connect(ws_url) as ws:
        print("Connected to GLC Gateway WebSocket!")
        offset = 0

        async def poll_telegram() -> None:
            nonlocal offset, owner_id
            async with httpx.AsyncClient() as client:
                while True:
                    try:
                        url = f"https://api.telegram.org/bot{token}/getUpdates"
                        resp = await client.get(url, params={"offset": offset, "timeout": 10}, timeout=15)
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get("ok"):
                                for update in data["result"]:
                                    offset = update["update_id"] + 1
                                    message = update.get("message") or {}
                                    from_user = message.get("from") or {}
                                    user_id = from_user.get("id") or message.get("chat", {}).get("id")

                                    # Auto-pair the first sender as owner
                                    if user_id and not owner_id:
                                        owner_id = str(user_id)
                                        store.force_pair_owner("telegram", owner_id, user_handle="owner")
                                        print(f"\n*** Auto-paired user {owner_id} as the owner! ***\n")

                                    print(f"Received Telegram Update ID: {update['update_id']}")

                                    # Translate to ChannelMessage
                                    msg = await adapter.on_message(update)
                                    if msg:
                                        print(f"Sending ChannelMessage to gateway: {msg.text}")
                                        await ws.send(msg.model_dump_json())
                                    else:
                                        print("Update dropped (not allowed or no message)")
                        elif resp.status_code == 409:
                            print(
                                "Conflict: another webhook or long poll is running for this bot. Please stop it."
                            )
                            await asyncio.sleep(5)
                        else:
                            print(f"Telegram API getUpdates returned status {resp.status_code}")
                    except Exception as e:
                        print(f"Error polling Telegram: {e}")
                    await asyncio.sleep(1)

        async def receive_from_gateway() -> None:
            while True:
                try:
                    raw_data = await ws.recv()
                    data = json.loads(raw_data)

                    if "error" in data:
                        print(f"Gateway error: {data['error']}")
                        continue

                    reply = ChannelReply.model_validate(data)
                    print(f"Received ChannelReply from gateway: {reply.text}")

                    # Dispatch via adapter
                    sent_info = await adapter.send(reply)
                    print(f"Sent reply to Telegram. API Response: {sent_info}")
                except websockets.exceptions.ConnectionClosed:
                    print("Gateway connection closed.")
                    break
                except Exception as e:
                    print(f"Error receiving from gateway / sending to Telegram: {e}")

        # Run both tasks concurrently
        await asyncio.gather(poll_telegram(), receive_from_gateway())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.")
