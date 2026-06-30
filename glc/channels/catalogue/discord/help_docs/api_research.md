# Discord API Research & Mapping

This document maps the real Discord REST and WebSocket gateway shapes relevant to the Discord channel adapter implementation in GLC v1.

---

## 1. `MESSAGE_CREATE` Gateway Dispatch Payload Structure
When a client connects to the Discord WebSocket Gateway (e.g. `wss://gateway.discord.gg`), it receives events as Gateway Payload JSON envelopes. For a new message event, the outer payload and the inner `"d"` parameter are structured as follows:

### Gateway Event Wrapper Structure
```json
{
  "op": 0,
  "s": 105,
  "t": "MESSAGE_CREATE",
  "d": {
    "id": "123456789012345678",
    "channel_id": "987654321098765432",
    "guild_id": "112233445566778899",
    "content": "Hello Agent! <@998877665544332211>",
    "timestamp": "2026-06-30T14:15:00.000000+00:00",
    "author": {
      "id": "111222333444555666",
      "username": "coder_bob",
      "discriminator": "0000",
      "global_name": "Bob the Builder",
      "avatar": "a_1234567890abcdef1234567890abcdef",
      "bot": false
    },
    "mentions": [
      {
        "id": "998877665544332211",
        "username": "glc_bot",
        "discriminator": "1234",
        "global_name": "GLC Gateway Agent",
        "avatar": "b_1234567890abcdef1234567890abcdef",
        "bot": true
      }
    ],
    "attachments": [],
    "type": 0
  }
}
```

### Key Parameter Mappings
* **`id`**: Snowflake string representing the unique message ID.
* **`channel_id`**: Snowflake string representing the Discord channel ID (corresponds to `ChannelMessage.thread_id`).
* **`guild_id`**: Snowflake string for the Server/Guild (absent/null in Direct Messages).
* **`content`**: Raw text content string (corresponds to `ChannelMessage.text`).
* **`timestamp`**: ISO 8601 formatted datetime string (e.g., `YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM`).
* **`author`**: The user who sent the message (mapped to `ChannelMessage.channel_user_id` and `user_handle`):
  * `id`: Snowflake string of the sender.
  * `username`: Unique username handle.
  * `global_name`: Optional display name.
  * `bot`: Boolean indicating if the sender is a bot.
* **`mentions`**: Array of mentioned users (used for mention resolution behavior).

---

## 2. REST API URL Structure

### A. Message Creation (Outbound Send)
Dispatches a message to a specific Discord text channel.
* **HTTP Method**: `POST`
* **URL**: `https://discord.com/api/v10/channels/{channel_id}/messages`
* **Request JSON Body Parameters**:
  ```json
  {
    "content": "Hello back!",
    "tts": false,
    "embeds": []
  }
  ```
* **Notes**: `tts` must default to `false` and should be omitted from the request body unless explicitly requested by the channel user to avoid unprompted audio speech in the client.

### B. User Profile Retrieval
Retrieves details for a specific user ID to resolve handles or verify metadata.
* **HTTP Method**: `GET`
* **URL**: `https://discord.com/api/v10/users/{user_id}`
* **Response Payload**: Returns a standard Discord User Object:
  ```json
  {
    "id": "111222333444555666",
    "username": "coder_bob",
    "discriminator": "0000",
    "global_name": "Bob the Builder",
    "avatar": "a_1234567890abcdef1234567890abcdef",
    "bot": false
  }
  ```

---

## 3. Required Headers
To interact with Discord's v10 API endpoints, requests must include the following headers:

1. **`Authorization`**: 
   * Format: `Bot <bot_token>`
   * Example: `Authorization: Bot MTIzNDU2Nzg5MDEyMzQ1Njc4.Y29kZXI.Ym9i`
2. **`Content-Type`**: 
   * Format: `application/json` (required for all `POST` / `PATCH` payloads).
3. **`User-Agent`**: 
   * Format: `DiscordBot (<repository_url>, <version_string>)`
   * Example: `User-Agent: DiscordBot (https://github.com/jssunil/glc_v1_g2_discord, 0.1.0)`
