"""Standalone script to test outbound Discord message API.

Reads credentials from .env and sends a test message directly to a target channel.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from glc.channels.catalogue.discord.run_discord_bridge import RealDiscordClient

# Load environment variables from .env at repository root
load_dotenv(Path(__file__).parent.parent.parent.parent.parent / ".env")


async def main():
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_TEST_CHANNEL_ID")

    if not bot_token:
        print("ERROR: DISCORD_BOT_TOKEN is not set in environment or .env", file=sys.stderr)
        return

    if not channel_id or channel_id == "your_discord_channel_id_here":
        print("DISCORD_TEST_CHANNEL_ID is not configured in .env", file=sys.stderr)
        try:
            channel_id = input("Please enter the Discord Channel ID to send a test message to: ").strip()
        except KeyboardInterrupt:
            print("\nCancelled.")
            return
        if not channel_id:
            print("ERROR: No channel ID provided.", file=sys.stderr)
            return

    print(f"[test] initializing Discord client and target channel: {channel_id}...")
    client = RealDiscordClient(token=bot_token)
    client.current_channel_id = channel_id

    # Construct the payload format expected by client.send
    payload = {"content": "Hello from GLC Discord Test Script! 🚀"}

    try:
        result = await client.send(payload)
        if result.get("status") == 429:
            print(f"FAILED: Rate limited. Retry after {result.get('retry_after')}s", file=sys.stderr)
        else:
            print(f"SUCCESS! Message sent successfully. Message ID: {result.get('id')}")
    except Exception as e:
        print(f"ERROR: Failed to send message: {e!r}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
