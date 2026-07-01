# Matrix (client-server API)

Channel adapter for [Matrix](https://spec.matrix.org/v1.10/client-server-api/).
Translates Matrix's `/sync` wire format to and from the typed GLC
envelope (`ChannelMessage` / `ChannelReply`). The agent runtime never
sees a raw Matrix event — only the envelope.

## Architecture

The adapter subclasses `glc.channels.base.ChannelAdapter` and implements
the two-method contract:

| Direction | Method            | Translation                                                                 |
|-----------|-------------------|-----------------------------------------------------------------------------|
| Inbound   | `on_message(raw)` | Matrix `/sync` response → `ChannelMessage`                                   |
| Outbound  | `send(reply)`     | `ChannelReply` → `PUT .../send/m.room.message` body `{msgtype, body}`        |

Inbound flow (`on_message`):

1. **Consume reconnect state** — if the connection dropped, swallow the
   flag and keep parsing; a reconnect must never raise.
2. **Locate the event** — `_first_timeline_event` walks
   `rooms.join.{room_id}.timeline.events` and returns the first
   `m.room.message` (stamping `room_id` onto it, since the event body
   does not carry it inside the timeline).
3. **Classify trust** — `glc.security.trust_level.classify("matrix", sender)`.
   Trust is decided in deterministic code, never by the model
   (GLC architectural move #5).
4. **Public-channel gate** — in a public room, an unknown, un-mentioned
   sender is dropped via `glc.security.allowlists.allowed()`.
5. **Resolve media** — `m.image`/`m.audio`/`m.video`/`m.file` events
   carry an `mxc://` URI in `content.url`. The adapter dereferences it
   to bytes and stores an `art:<sha>` artifact handle. The raw `mxc://`
   is kept only under `Attachment.metadata` for traceability.
6. **Build the envelope** — map sender, display name, body, thread,
   millisecond `origin_server_ts` → UTC `datetime`, and Matrix-specific
   ids (`room_id`, `event_id`, `msgtype`) into `metadata`.

Outbound flow (`send`) emits the exact Matrix shape
`{"msgtype": "m.text", "body": "..."}`. Audio/attachment replies switch
`msgtype` and add a `url`. A rate-limited send returns the upstream
`M_LIMIT_EXCEEDED` / `429` error dict unchanged rather than raising.

`schemas.py` is intentionally empty — the canonical envelope in
`glc.channels.envelope` covers everything Matrix needs.

## Required environment variables

For a real homeserver (the test suite needs none of these — it runs
fully against the mock):

- `MATRIX_HOMESERVER`
- `MATRIX_USER_ID`
- `MATRIX_ACCESS_TOKEN`

## Free-tier limits

matrix.org is free; self-hosted Synapse / Dendrite cost nothing beyond
infrastructure. No paid API is used anywhere in the shipped adapter.

## Channel quirks we hit

- **`mxc://` is not a fetchable URL.** Media events reference content by
  an opaque `mxc://server/mediaId` URI that must be downloaded through
  `/_matrix/media/v3/download/...`. Surfacing the raw `mxc://` as an
  attachment ref would hand the runtime a handle it cannot dereference,
  so we resolve it to bytes and emit an `art:<sha>` handle instead.
- **Millisecond timestamps.** `origin_server_ts` is epoch
  *milliseconds*; the envelope wants a `datetime`, so we divide by 1000
  and attach UTC.
- **Deeply nested sync.** A single message lives at
  `rooms.join.{room_id}.timeline.events[]`, and the event object does
  not repeat its own `room_id` — we stamp it on during parsing.
- **Federated senders.** mxids look like `@user:other.server`. A
  federated stranger is just another unpaired sender → `untrusted`.
- **End-to-end encryption.** E2EE rooms require olm/megolm setup before
  plaintext events arrive. Out of scope for this adapter (plaintext
  rooms only); noted as a known limitation.

## How the tests exercise the trust-level boundary

`tests/channels/test_matrix.py` drives the boundary from both sides
using the pairing store:

- `test_on_message_owner_returns_valid_envelope` force-pairs the owner
  (`force_pair_owner`) and asserts the inbound envelope carries
  `trust_level == "owner_paired"`.
- `test_on_message_stranger_is_untrusted` sends the **same** message
  from an unpaired mxid and asserts `trust_level == "untrusted"` — the
  only variable is identity, so it isolates the classifier.
- `test_allowlist_silently_drops_stranger_in_public` sets
  `config["is_public_channel"] = True` and asserts an unknown sender is
  dropped (`None`) or untrusted — proving the public-channel allowlist
  gate runs before the message reaches the runtime.

Because `classify()` reads the same `~/.glc/pairings.sqlite` store the
rest of GLC uses, the test's pairing setup and the adapter's runtime
decision share one source of truth — a bad inbound message cannot
upgrade its own trust level.

## Tests

```sh
uv run pytest tests/channels/test_matrix.py -v   # 7 passed
uv run ruff check glc/channels/catalogue/matrix/
uv run mypy  glc/channels/catalogue/matrix/
```

The mock-API fake at `tests/channels/mocks/matrix_mock.py` is the fixed
contract surface; the adapter is written against it and never edits it.
