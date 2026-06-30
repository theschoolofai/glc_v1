# Generic Webhook (HTTP in/out)

Stateless HTTP adapter for generic signed webhooks. Inbound requests are
authenticated using **Stripe/SVIX-style HMAC-SHA256 signatures**; outbound
replies are POSTed to a configured callback URL.

## Inbound authentication

Every inbound POST must carry the header:

```
X-Webhook-Signature: t=<unix_timestamp>,v1=<hex_hmac_sha256>
```

The adapter reconstructs the signed string `f"{t}.{raw_body}"`, computes
`HMAC-SHA256` using `WEBHOOK_SHARED_SECRET`, and compares it against `v1`
with a constant-time `hmac.compare_digest` to prevent timing attacks.

### Replay window

After verifying the signature, the adapter checks `abs(time.time() - t) <= 300`.
Any request older than **5 minutes** — or with a future timestamp beyond that
window — is rejected, even if the HMAC is correct. This closes the replay-attack
vector: a captured valid request cannot be re-submitted later.

Unsigned bodies, missing/malformed `X-Webhook-Signature`, bad HMAC, or expired
timestamps all cause `on_message` to return `None`. The gateway drops the event
silently and nothing is forwarded to the agent.

## Environment variables

| Variable | Direction | Purpose |
|---|---|---|
| `WEBHOOK_SHARED_SECRET` | inbound | HMAC key; must match the secret registered with the caller |
| `WEBHOOK_DEFAULT_TARGET_URL` | outbound | URL to POST replies to |

## Trust model

| Sender | Trust level |
|---|---|
| Paired as owner via `force_pair_owner` | `owner_paired` |
| Paired via normal pairing flow | `user_paired` |
| Unknown sender | `untrusted` |

In public-channel mode (`config["is_public_channel"] = True`), untrusted
senders are checked against the channel's `allowed_senders` allowlist in
`channels.yaml`. Senders not on the list are silently dropped.

## Outbound wire format

```json
{ "recipient_id": "<channel_user_id>", "text": "<reply text>" }
```

The payload is POSTed as JSON to `WEBHOOK_DEFAULT_TARGET_URL`. If no target
URL is configured, the payload is returned unchanged (handy in tests). A
JSON response is returned as-is; a non-JSON response is returned as
`{"status": <code>, "text": ...}`.

## schemas.py

`WebhookInbound` is a Pydantic model that validates the parsed JSON body of
every inbound webhook event after signature verification passes:

| Field | Type | Description |
|---|---|---|
| `sender_id` | `str` | Unique ID of the sending system/user |
| `sender_handle` | `str` | Human-readable display name (required) |
| `text` | `str \| None` | Message text payload |
| `metadata` | `dict` | Arbitrary extra fields forwarded into `ChannelMessage.metadata` |

## Adapter helpers + methods

### `_verify(raw_body, headers) -> bool`

Private helper. Parses `X-Webhook-Signature`, validates HMAC-SHA256, and
enforces the 5-minute replay window. Returns `True` only when the signature
is valid and the timestamp is fresh, otherwise `False`. Called at the top of
`on_message` so all auth logic stays in one place.

### `on_message(raw) -> ChannelMessage | None`

Accepts a dict `{"raw_body": bytes, "headers": dict}`. Calls `_verify`,
parsing the body with `WebhookInbound`, classifies trust via
`glc.security.trust_level.classify()`, applies the public-channel allowlist
if needed, and returns a `ChannelMessage`. Returns `None` on any auth or
validation failure, and also handles mock disconnects gracefully.

### `send(reply) -> Any`

Builds `{"recipient_id": ..., "text": ...}` and dispatches it. In test mode
(`config["mock"]`) it calls `mock.send(payload)` directly. In production it
POSTs to `WEBHOOK_DEFAULT_TARGET_URL` via `httpx`, propagating any HTTP
error response (including 429) back to the caller.
