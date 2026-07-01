"""Live integration tests for the Discord channel adapter.

These tests require a real Discord bot token and test channel and are
skipped automatically when credentials are absent, so CI always passes.

Prerequisites
-------------
Set the following in your .env file at the repository root:

    DISCORD_BOT_TOKEN=<your bot token>
    DISCORD_TEST_CHANNEL_ID=<channel the bot can post to>
    DISCORD_TEST_USER_ID=<any valid user ID, for get_user resolution>

Required bot configuration in the Discord Developer Portal:
    - Privileged Gateway Intents: Message Content Intent, Server Members Intent
    - Bot Permissions: Send Messages, Read Messages/View Channels

Run with:
    uv run pytest glc/channels/catalogue/discord/tests/ -m requires_live_api -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from glc.channels.catalogue.discord.adapter import Adapter
from glc.channels.catalogue.discord.run_discord_bridge import RealDiscordClient
from glc.channels.envelope import ChannelReply

load_dotenv(Path(__file__).resolve().parents[6] / ".env")

BOT_TOKEN: str = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID: str = os.environ.get("DISCORD_TEST_CHANNEL_ID", "")
TEST_USER_ID: str = os.environ.get("DISCORD_TEST_USER_ID", "")

pytestmark = pytest.mark.requires_live_api

_skip_no_send = pytest.mark.skipif(
    not BOT_TOKEN or not CHANNEL_ID,
    reason="DISCORD_BOT_TOKEN or DISCORD_TEST_CHANNEL_ID not set",
)
_skip_no_token = pytest.mark.skipif(
    not BOT_TOKEN,
    reason="DISCORD_BOT_TOKEN not set",
)


@pytest.fixture
def real_client() -> RealDiscordClient:
    return RealDiscordClient(token=BOT_TOKEN)


@_skip_no_send
@pytest.mark.asyncio
async def test_send_real_message(real_client: RealDiscordClient) -> None:
    """adapter.send() via RealDiscordClient posts to a real Discord channel
    and receives a message ID in the response."""
    real_client.current_channel_id = CHANNEL_ID
    adapter = Adapter(config={"client": real_client})
    reply = ChannelReply(channel="discord", channel_user_id="live-test", text="[GLC live test] ping")

    result = await adapter.send(reply)

    assert isinstance(result, dict), f"expected dict response, got {type(result)}"
    assert result.get("status") != 429, f"rate limited: {result}"
    assert "id" in result, f"expected message id in Discord response, got: {result}"


@_skip_no_token
def test_get_user_resolves_handle(real_client: RealDiscordClient) -> None:
    """RealDiscordClient.get_user() returns a valid user dict for a known user ID."""
    if not TEST_USER_ID:
        pytest.skip("DISCORD_TEST_USER_ID not set")

    user = real_client.get_user(TEST_USER_ID)

    assert user is not None, "expected a user dict, got None"
    assert "id" in user, f"missing 'id' field in user response: {user}"
    assert "username" in user, f"missing 'username' field in user response: {user}"
