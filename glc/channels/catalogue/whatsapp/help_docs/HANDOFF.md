# HANDOFF.md — Group WhatsApp (G21), GLC v1 Session 11

**Slot:** `whatsapp` · **Owned path:** `glc/channels/catalogue/whatsapp/` (and everything under it)
**Fork owner:** Raghu Rammohan (`rraghu214`)
**Repo:** `theschoolofai/glc_v1` (public, MIT, Python 3.11 + FastAPI)

This document is written so any team member can pick a story, read only their
section, and ship a real, independently-attributable commit — without needing
to read the rest of this file or ask the fork owner what to do first.

**Two independent numbering systems are used below, on purpose — don't
conflate them:** section numbers (`§0`–`§11`) number this *document's*
structure top to bottom. Story numbers (`US-1`–`US-15`, plus backlog
`B1`–`B3`) number the *build sequence* your team executes. They are not the
same axis and don't line up numerically. Every cross-reference below names
the destination ("the Meta setup walkthrough, §8") rather than relying on
the bare number alone, to avoid confusion.

---

## §0. Confirmed facts vs. open items

Everything in this document is derived directly from reading the live repo
(`theschoolofai/glc_v1` on `main`, fetched directly) and the fixed test/mock
files for this slot. Where something is genuinely unresolved, it's flagged
here instead of guessed.

### §0.1 Confirmed, not assumptions
- There is **no Claim PR**. The live repo's own README states assignments
  are fixed in `GROUPS.md` and "there is no claim PR." Skip that step
  entirely, even though the LMS page and `docs/ADAPTER_GUIDE.md` still
  describe one — the repo wins.
- Owned path is exactly `glc/channels/catalogue/whatsapp/` and everything
  under it (`/**`, any depth — confirmed directly against `GROUPS.md`'s
  table row). Nothing else.
- `tests/channels/test_whatsapp.py` and `tests/channels/mocks/whatsapp_mock.py`
  are fixed — outside the owned path, explicitly marked "do not edit" in
  the stub README, and exercise **only the Meta wire format**. They cannot
  be made to exercise Twilio — confirmed directly: the mock has no method
  that produces a Twilio-shaped fixture, the assertions check Meta's exact
  JSON body shape, and the file is read-only regardless. Passing all 7
  fixed tests proves nothing about whether the Twilio code path works.
- The Admin confirmed live in the Session 11 Q&A that **both** Meta Cloud
  API and Twilio Sandbox wire formats are required in code for this one
  slot — not graded by the CI mock (Meta-only), but required for the
  manual "make it usable" review bar.
- A free **test** WhatsApp number/account (no business verification) is
  explicitly sufficient — the Admin said "yes, of course" when asked
  directly. Production verification is not required.
- The CI scorecard is computed by an actual, locally-runnable script —
  `scripts/scorecard.py` — read directly from its source: 6 structural
  tests (1 pt each), 1 behavioural test (2 pts), `ruff` (0.5 pt), `mypy`
  (0.5 pt), PR template completeness (0.5 pt, regex on the PR body), and
  adapter discipline (0.5 pt, string search for forbidden imports and for
  `trust_level`/`classify` in source) — 10 pts, scaled ×200. See `US-12`
  and `US-15`.
- `GROUPS.md`'s shared-code exception, quoted exactly: *"Changes outside
  any slot's owned paths require: a separate PR scoped only to the shared
  code, `@theschoolofai` review, [and] branch-protection bypass for the
  boundary check (the check passes trivially because the PR has no group
  marker)."* Relevant to backlog item `B3` — see §7.16.
- Twilio's signature scheme is **not** a variant of Meta's — confirmed via
  Twilio's own documentation: HMAC-**SHA1** over the *full webhook URL
  plus all POST params sorted alphabetically and concatenated as
  key+value pairs*, base64-encoded. Meta uses HMAC-**SHA256** over the raw
  body bytes alone, hex-encoded. These need two genuinely separate
  functions — see `US-3` vs `US-6`.
- Twilio's inbound webhook carries **no timestamp field at all** —
  confirmed against a real sample payload (fields present: `MessageSid`,
  `AccountSid`, `From`, `To`, `Body`, `NumMedia`, `ProfileName`, `WaId`,
  `ApiVersion`). Meta's `messages[0].timestamp` has no Twilio equivalent —
  see `US-7`.

### §0.2 Open / not yet locked — confirm before the final push
- **Deadline conflict.** The LMS top banner reads "Due Mon, Jul 6, 2026,
  3:30 AM," but the Late Policy text and the deadlines table both say the
  review window closes **Sun, Jul 5**. The fork owner is confirming this with a TA.
  This doc targets finishing **well before Jul 1** regardless.
- The exact GitHub handles of teammates beyond the fork owner aren't recorded here.
  Branch names below use placeholders like `<your-github-handle>` — swap
  in your real one.
- **`twilio` not yet declared in `pyproject.toml` (pending separate PR to TSAI).**
  `adapter.py` (US-6) and `glc/channels/catalogue/whatsapp/tests/test_twilio_path.py`
  (US-11) both import from the `twilio` package. `pyproject.toml` is outside the
  owned path — adding a dependency requires a **separate PR scoped only to
  `pyproject.toml`, `@theschoolofai` review, and branch-protection bypass** (see
  §0.1's shared-code exception). Until that PR merges, `adapter.py` will raise
  `ModuleNotFoundError` on a clean install. Raise this PR before `US-9` branches
  from `integration`.

### §0.3 Authorization/policy gaps — found by re-reading `glc/routes/channels.py`,
`glc/security/rate_limits.py`, and `tests/test_audit_log.py` directly
- Inbound is well-guarded twice over (your adapter's own check, plus the
  gateway's independent re-check). **Outbound was not guarded at all**
  until `US-10` was revised to add a pairing-presence check. Confirmed by
  reading `ChannelReply`'s schema (no validation on `channel_user_id`) and
  `channels.py` (no equivalent check exists anywhere for sends).
- `RateLimiter` only exposes `check_message()` (inbound) and
  `check_tool_call()` — no outbound-send rate limit anywhere in the shared
  code. Worth a defensive throttle in `send()` if time allows — see
  backlog item `B2`'s sibling concern, not required.
- The gateway logs `inbound_message`, `allowlist_drop`, and `rate_limit`,
  but never logs the outbound reply it sends, in the shipped code as it
  stands today. `US-10` recommends (not requires) logging this ourselves.
- `is_public_channel`/`was_mentioned` exist in the allowlist contract for
  generic adapter-test-pattern reasons, but Meta's Cloud API has no
  group-chat or @mention concept at all. **This is just a fact about our
  slot, not a gap — no escalation needed.**

### §0.4 Questions worth raising with the Admin/TA (not blocking, course-wide scope)
1. **Tool governance for channel sends.** `policy.yaml`'s shipped rules
   govern *tool calls*, not a channel adapter's `send()`. Is that
   intentional (agent runtime is still a stub), or should adapters
   self-police in the interim?
2. **No outbound rate limiting anywhere in shared code.** Planned later,
   or each adapter's own responsibility?
3. **No outbound audit logging in the gateway.** Planned gateway-side, or
   should adapters log their own sends?

None of these three block our own PR. All three are shared-code gaps
outside our owned path, affecting all 15 channels — raise once in the
general S11 channel, not G21-specific.

---

## §1. What GLC v1 is, in two paragraphs

GLC v1 is a gateway. It already handles text chat, vision, embeddings, cost
tracking, and LLM provider routing (built in earlier sessions). Session 11
adds the **channel layer** — adapters that translate a chat platform's wire
format into a typed envelope the agent runtime understands, and translate
the agent's reply back out.

Your group owns exactly one adapter slot — `whatsapp` — but that slot must
speak **two** upstream wire formats per the Admin's explicit instruction:
Meta's Cloud API and Twilio's Sandbox API. The agent itself is **not**
your code — it's the S9 runtime, outside your owned path. Your adapter's
job is translation, for both providers: turn an inbound webhook into a
`ChannelMessage`, and turn the agent's `ChannelReply` into the correct
provider's outbound API call.

---

## §2. The contract — files you read but never edit

These live in `glc/channels/` and `glc/security/`, outside your owned path.

### §2.1 `glc/channels/envelope.py`
```python
class ChannelMessage(BaseModel):
    channel: str
    channel_user_id: str
    user_handle: str
    text: str | None = None
    attachments: list[Attachment] = []
    voice_audio_ref: str | None = None
    thread_id: str | None = None
    trust_level: Literal["owner_paired", "user_paired", "untrusted"]
    arrived_at: datetime
    metadata: dict[str, Any] = {}
    # extra="forbid" — no extra fields allowed

class ChannelReply(BaseModel):
    channel: str
    channel_user_id: str
    text: str | None = None
    attachments: list[Attachment] = []
    voice_audio_ref: str | None = None
    thread_id: str | None = None
    # also extra="forbid"
```
Don't smuggle provider-specific data onto `ChannelMessage` directly — use
`metadata: dict`, e.g. `metadata={"provider": "twilio"}`.

### §2.2 `glc/channels/base.py`
```python
class ChannelAdapter(ABC):
    name: str = ""
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def on_message(self, raw: Any) -> ChannelMessage: ...

    @abstractmethod
    async def send(self, reply: ChannelReply) -> Any: ...
```
One adapter class, two providers — the dispatch happens *inside*
`on_message`/`send`, not via two separate adapter classes.

### §2.3 `glc/security/trust_level.py`
```python
def classify(channel: str, channel_user_id: str) -> TrustLevel:
    # owner_paired / user_paired / untrusted, looked up from the pairing store
```

### §2.4 `glc/security/allowlists.py`
```python
def allowed(
    channel: str, channel_user_id: str, *,
    owner_ids: list[str] | None = None,
    is_public_channel: bool = False,
    was_mentioned: bool = False,
) -> tuple[bool, str]:
```

### §2.5 `glc/security/pairing.py`
```python
get_pairing_store().owners(channel: str | None) -> list[PairingRecord]
get_pairing_store().lookup(channel: str, channel_user_id: str) -> PairingRecord | None
```

### §2.6 Inbound vs. outbound authorization — not symmetric, on purpose to flag
`glc/routes/channels.py` already re-checks `allowed()` and rate-limits
every *inbound* message, and audit-logs every step. Nothing in the shared
code does the equivalent for outbound sends — see `US-10`'s pairing guard.

### §2.7 Helper function names are your team's choice, not the test's
None of the helper function names used in §7 are imported by the fixed
test file — it only ever calls `Adapter(...).on_message(...)` and
`Adapter(...).send(...)`. Keep names consistent across your team for
clean integration, but they aren't gospel.

---

## §3. `whatsapp_mock.py` — what each method does (plain English)

| Method | What it does |
|---|---|
| `queue_owner_message(text)` | Pretends the paired owner just texted you (Meta shape). |
| `queue_stranger_message(text)` | Pretends a random unknown number just texted you (Meta shape). |
| `queue_signed_webhook(...)` | Returns `(raw_bytes, headers)` for a correctly signed Meta webhook. |
| `queue_unsigned_webhook(...)` | Same, no signature header — simulates a direct hit bypassing Meta. |
| `queue_tampered_webhook(...)` | Same, signed with the wrong secret. |
| `send(payload)` *(async)* | Pretends to be Meta's send endpoint; logs to `mock.send_log`, or returns a fake 429. |
| `force_disconnect()` / `pop_disconnect()` | Simulated connection-drop flag — never actually reaches `on_message`'s input; see §4.2. |
| `record_envelope_constructed()` | Optional counter, not required by any of the 7 tests. |
| `_text_webhook(...)` *(internal)* | The precise spec for the Meta JSON shape your parser must handle. |
| `_sign(body, secret)` *(internal)* | Meta's signing scheme — mirror image of `verify_meta_signature`. |

Fixed values: `OWNER_WA_ID = "919999990000"`, `STRANGER_WA_ID = "917777770000"`,
`PHONE_NUMBER_ID = "10987654321"`, `DEFAULT_APP_SECRET = "test-app-secret"`.
**All Meta-only** — there is no Twilio equivalent mock anywhere in the repo.

---

## §4. `test_whatsapp.py` — what each test actually checks (plain English)

### §4.1 The 7 tests (Meta only)

| # | Test | What it's really checking |
|---|---|---|
| 1 | `test_on_message_owner_returns_valid_envelope` | Owner sends a message → wrapped correctly, `trust_level == "owner_paired"`. |
| 2 | `test_on_message_stranger_is_untrusted` | Unknown number → labeled `"untrusted"`. |
| 3 | `test_send_emits_valid_wire_payload` | Outbound JSON exactly matches Meta's Graph API shape. |
| 4 | `test_disconnect_is_handled` | No crash on a forced disconnect. |
| 5 | `test_rate_limit_propagates_429` | A 429 is returned, not swallowed. |
| 6 | `test_allowlist_silently_drops_stranger_in_public` | Stranger in public context quietly dropped. |
| 7 | `test_channel_specific_behaviour_signature_verification` | **400-point test.** Unsigned/tampered → reject; valid → accept. |

### §4.2 The one non-obvious detail every Meta story depends on

`on_message(raw)` is called with **two different shapes**:

| Shape | Looks like | Used by | Meaning |
|---|---|---|---|
| **A** | Bare dict — already-decoded webhook body | Tests 1, 2, 4, 6 | "Signature already verified upstream." |
| **B** | `{"raw_body": bytes, "headers": dict}` | Test 7 only | "Verify the signature first, then decode." |

In real production, every actual call is Shape B. Shape A exists only so
the test suite can test trust-classification in isolation. The same
detect-shape logic extends naturally to Twilio in `US-9` — Twilio's
`raw_body` will be form-urlencoded bytes rather than JSON, distinguished
by which signature header is present.

**On test 4 (disconnect):** the disconnect flag never reaches
`on_message`'s input — it's a no-op test for webhook-style channels,
passes for free once test 1 passes. Don't build disconnect-detection
logic for it.

---

## §5. Do's and Don'ts

### §5.1 You may touch
- `glc/channels/catalogue/whatsapp/adapter.py` (required)
- `glc/channels/catalogue/whatsapp/schemas.py` (optional — backlog `B1`)
- `glc/channels/catalogue/whatsapp/README.md` (required in practice)
- `glc/channels/catalogue/whatsapp/tests/test_twilio_path.py` (new, `US-11`
  — inside our owned path, no special process; see §7.11 and §0.1)
- Any other new file inside that same folder — the boundary check covers
  the whole folder recursively.

### §5.2 You may never touch
- `tests/channels/test_whatsapp.py`, `tests/channels/mocks/whatsapp_mock.py`
  — fixed, outside owned path.
- `glc/channels/envelope.py`, `glc/channels/base.py`, `glc/security/*.py`
  — shared contract/security layer.
- Any other group's `glc/channels/catalogue/<other-name>/`.
- `GROUPS.md`, `.github/workflows/*`, `policy.yaml` — maintainer-owned.

### §5.3 Hard constraints (apply to shipped code)
- No paid APIs in shipped code. No third-party agentic frameworks.
- No hardcoded secrets — real values live only in a local, gitignored
  `.env` (confirmed: `.gitignore` already excludes `.env` and `.env.*`).
  Document required variables in `README.md` instead of committing an
  example file.
- `trust_level.classify()` must be called for every inbound message,
  **for both providers**, before a `ChannelMessage` is constructed.
- Signature verification must happen *before* any parsing — not after,
  not in parallel — **for both providers**.

---

## §6. Git workflow — fork → mini-PRs → integration branch → final PR

**Repo:** `rraghu214/glc_v1_whatsapp` (corrected from an earlier draft that
said `glc_v1` — confirmed against the actual fork). **Integration branch:**
`integration` — renamed from an earlier `raghu_v1`, since this fork only
ever has one integration branch and the descriptive name reads clearer to
anyone glancing at branch names later.

### §6.1 One-time setup (fork owner)
```bash
git clone https://github.com/rraghu214/glc_v1_whatsapp.git
cd glc_v1_whatsapp
git checkout -b integration
git push -u origin integration
```
Also: GitHub UI → Settings → Actions → General → allow workflows to run on
the fork (disabled by default on forks).

**If renaming an existing `raghu_v1` branch instead of creating fresh:**
```bash
git checkout raghu_v1
git branch -m raghu_v1 integration
git push origin -u integration
git push origin --delete raghu_v1
```
Anyone who already cloned the repo won't see this rename automatically —
they need `git fetch && git checkout integration` next time they pull, or
their local `raghu_v1` silently goes stale with no error.

### §6.2 Branching strategy — one hub, every story is a spoke

`integration` is the **only** branch anything ever merges into before the
final PR. No story's branch merges into another story's branch directly —
not even the orchestrators (`US-9`, `US-10`), which depend on earlier
stories' *code*, not their *branches*.

```
feature/us3-verify-meta-signature  ─┐
feature/us4-parse-meta-payload     ─┼──► mini-PR ──► integration
feature/us6-verify-twilio-signature─┤
feature/us7-parse-twilio-payload   ─┘
                                           │
                              integration now contains US-3/4/6/7
                                           │
                    feature/us9-on-message branches FROM integration
                    (only created once the above show Done on the
                    task sheet — branching earlier means missing their
                    merged code and rebasing later)
                                           │
                                           ▼ mini-PR back into
                                       integration
```

Same pattern for `US-5`/`US-8` → `US-10`, and for every later story off
whatever `integration` contains at that point.

### §6.3 Per-story setup (everyone else)
```bash
git clone https://github.com/rraghu214/glc_v1_whatsapp.git
cd glc_v1_whatsapp
git checkout integration
git pull
git checkout -b feature/us<N>-<short-name>
# ... do the work ...
git add glc/channels/catalogue/whatsapp/
git commit -m "US-<N>: <what you did>"
git push -u origin feature/us<N>-<short-name>
```
Open a mini-PR inside the fork: base = `integration`. Reviewed and
merged by whoever is running `US-12` (QA) that day.

**Timing differs by wave:** Wave 1 (`US-1`–`US-8`) has no predecessors, so
all 8 can run this immediately, day one. Everything after — check the task
sheet's Predecessor Status column shows `✅ Ready to start` before running
`git checkout -b` at all.

### §6.4 Final step (once US-1 through US-14 are done — `US-15`)
Base = `theschoolofai/glc_v1:main`, compare =
`rraghu214/glc_v1_whatsapp:integration`. Full procedure in §10.

---

## §7. User stories — execution sequence


15 core stories. Wave 1 is fully parallel (8 stories, zero cross-dependency).
Wave 2 needs Wave 1 merged. The rest are sequential, gated by QA.

| # | Story | Depends on |
|---|---|---|
| `US-1` | Real-world wiring: Meta | Nothing |
| `US-2` | Real-world wiring: Twilio | Nothing |
| `US-3` | `verify_meta_signature` | Nothing |
| `US-4` | `parse_meta_payload` | Nothing |
| `US-5` | `build_meta_send_payload` | Nothing |
| `US-6` | `verify_twilio_signature` | Nothing |
| `US-7` | `parse_twilio_payload` | Nothing |
| `US-8` | `build_twilio_send_payload` | Nothing |
| `US-9` | `on_message` orchestrator (dual-provider) | `US-3`, `US-4`, `US-6`, `US-7` |
| `US-10` | `send` orchestrator (dual-provider + outbound guard) | `US-5`, `US-8` |
| `US-11` | Twilio safety-net test suite (Option A) | `US-6`–`US-8` to start; extends after `US-9`/`US-10` |
| `US-12` | QA / verification (recurring + gate) | `US-9`, `US-10`, `US-11` |
| `US-13` | Demo recording (both providers) | `US-12` green, `US-1`, `US-2` |
| `US-14` | README.md | `US-13` |
| `US-15` | Final PR | Everything above |

### §7.1 US-1 — Real-world wiring: Meta
**Do:** Follow §8 in full. Produces test phone number, access token, app
secret, tunnel, verified webhook subscription.
**Acceptance criteria:** a real WhatsApp message round-trips via the Graph API.
**Exit criteria:** no commit required; hand values to `US-14`/`US-13` owners.

### §7.2 US-2 — Real-world wiring: Twilio
**Do:** Follow §9 in full. Produces Account SID, Auth Token, sandbox
number, at least one joined recipient.
**Acceptance criteria:** a sandbox message round-trips.
**Exit criteria:** hand values to `US-14`/`US-13` owners.

### §7.3 US-3 — `verify_meta_signature`
**Branch:** `feature/us3-verify-meta-signature`
```python
import hmac, hashlib, os

def verify_meta_signature(raw_body: bytes, headers: dict) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    sig_header = headers.get("X-Hub-Signature-256", "")
    if not secret or not sig_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.removeprefix("sha256="))
```
**Acceptance criteria:** `True` for `queue_signed_webhook()`; `False` for
`queue_unsigned_webhook()`/`queue_tampered_webhook()`.
**Exit criteria / commit:** the function, with the 3 manual cases noted.

### §7.4 US-4 — `parse_meta_payload`
**Branch:** `feature/us4-parse-meta-payload`
**Do:** Walk `entry[0].changes[0].value`, pull `messages[0].from`,
`messages[0].text.body`, `messages[0].id`, `messages[0].timestamp`,
`contacts[0].profile.name`. **Required, not optional, from the start:**
- Return `None` if there's no `messages` key (Meta sends delivery-status
  webhooks for every message you send — including during `US-13`'s own
  demo — so this *will* happen, not might).
- If `messages[0].type != "text"`, return `text=None` rather than raising
  `KeyError` on a missing `text.body` — `from`/`id`/`timestamp`/profile
  name still populate normally.
**Acceptance criteria:** correct extraction for `queue_owner_message`/
`queue_stranger_message`; no exception on a hand-built status-only or
image-type payload.
**Exit criteria / commit:** the function plus manual checks for both
required edge cases above.

### §7.5 US-5 — `build_meta_send_payload`
**Branch:** `feature/us5-build-meta-send-payload`
```python
{"messaging_product": "whatsapp", "to": reply.channel_user_id,
 "type": "text", "text": {"body": reply.text}}
```
**Acceptance criteria:** matches `test_send_emits_valid_wire_payload` once wired in.

### §7.6 US-6 — `verify_twilio_signature`
**Branch:** `feature/us6-verify-twilio-signature`
**Do:** Twilio's scheme is genuinely different from Meta's — confirmed via
Twilio's docs: sort POST params alphabetically, concatenate key+value
pairs (no separator), append to the **full webhook URL**, HMAC-**SHA1**
with the Auth Token, base64-encode, compare to `X-Twilio-Signature`.
```python
import hmac, hashlib, base64

def verify_twilio_signature(url: str, params: dict, signature: str, auth_token: str) -> bool:
    sorted_kv = "".join(f"{k}{params[k]}" for k in sorted(params))
    data = (url + sorted_kv).encode()
    expected = base64.b64encode(hmac.new(auth_token.encode(), data, hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)
```
**Gotcha worth flagging:** this needs the *full public webhook URL*, not
just the body — something Meta's scheme never required. Source it from an
env var (`TWILIO_WEBHOOK_URL`) set to match exactly what's configured in
the Twilio console, since any mismatch (trailing slash, http vs https)
breaks validation.
**Acceptance criteria:** correctly validates a signature you compute by
hand against a sample form body, using a throwaway test Auth Token.
**Exit criteria / commit:** the function; feeds `US-11`.

### §7.7 US-7 — `parse_twilio_payload`
**Branch:** `feature/us7-parse-twilio-payload`
**Do:** Given Twilio's form-urlencoded fields — confirmed against a real
sample payload: `MessageSid`, `AccountSid`, `From` (`whatsapp:+1...`),
`To`, `Body`, `NumMedia`, `ProfileName`, `WaId` — extract:
- `from_id` = `WaId` (already a bare number, no `whatsapp:` prefix to strip)
- `text` = `Body` if `NumMedia == "0"`, else `None` (non-text/media
  message — handle this from day one here, unlike Meta where it was
  originally missed and had to be retrofitted)
- `message_id` = `MessageSid`
- `profile_name` = `ProfileName` if present, else `None` (not guaranteed
  on every payload)
- **`timestamp` — Twilio's inbound webhook includes no timestamp field at
  all**, confirmed against a real sample payload. Use the server's receipt
  time (`datetime.utcnow()`) instead, captured at the moment the webhook
  route receives the request, not inside this pure function — pass it in
  as a parameter so the function stays testable without mocking the clock.
**Acceptance criteria:** correct extraction from a hand-built sample
payload matching the confirmed field list; graceful `text=None` on a
media-only message.
**Exit criteria / commit:** the function; feeds `US-11`.

### §7.8 US-8 — `build_twilio_send_payload`
**Branch:** `feature/us8-build-twilio-send-payload`
```python
{"From": f"whatsapp:{TWILIO_WHATSAPP_FROM}",
 "To": f"whatsapp:{reply.channel_user_id}",
 "Body": reply.text}
# POSTed as form data (not JSON) to
# https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json
# with Basic Auth (Account SID / Auth Token)
```
**Acceptance criteria:** form body matches Twilio's documented shape;
manually verified against a real sandbox send (no fixed test exists).
**Exit criteria / commit:** the function; feeds `US-11`.

### §7.9 US-9 — `on_message` orchestrator (dual-provider)
**Branch:** `feature/us9-on-message` — start once `US-3`, `US-4`, `US-6`, `US-7` are merged
**Do:**
1. Detect provider: check which signature header is present
   (`X-Hub-Signature-256` → Meta; `X-Twilio-Signature` → Twilio), or fall
   back to payload shape (JSON with `"entry"` → Meta; form-urlencoded with
   `"From"`/`"Body"` → Twilio).
2. Dispatch to the matching verify+parse pair; if verification fails,
   return `None`.
3. Write the resolved provider to the shared module-level cache (see US-10
   for the cache definition):
   `provider_cache[parsed["from_id"]] = "meta"` or `"twilio"` accordingly.
   This write is **unconditional** — it happens on every inbound message
   that passes signature verification, every time, no exceptions and no
   conditional logic. Always overwrite whatever was there before. Last-seen
   provider always wins; there is no merge or comparison logic, since a plain
   dict write naturally replaces the old value with no trace of it remaining.
4. `trust_level.classify("whatsapp", parsed["from_id"])`.
5. `owner_ids = [r.channel_user_id for r in get_pairing_store().owners("whatsapp")]`.
6. `is_public = self.config.get("is_public_channel", False)`;
   `was_mentioned = False` always (neither Meta's Cloud API nor Twilio's
   WhatsApp integration has a group-chat/@mention concept).
7. `allowlists.allowed(...)`; if not allowed, return `None`.
8. Construct `ChannelMessage` with `metadata={"provider": "meta"}` or
   `{"provider": "twilio"}`.
**Acceptance criteria:** the 5 Meta-path fixed tests (1, 2, 4, 6, 7) still
pass; `US-11`'s Twilio-path tests pass once that suite exists.
**Exit criteria / commit:** merged; both test suites' relevant subsets green.

### §7.10 US-10 — `send` orchestrator (dual-provider + outbound guard)
**Branch:** `feature/us10-send` — start once `US-5`, `US-8` are merged
**Do:**
1. **Provider resolution** — positioned as the very first step in `send()`,
   before the pairing guard. Added because `ChannelReply` has no field to
   carry provider info (`extra='forbid'` in `envelope.py`, confirmed — do
   not add a field there or split into two Adapter subclasses).

   Define these at module level, shared with `on_message`'s cache write
   (US-9 step 3):
   ```python
   USE_PROVIDER_CACHE: bool = True   # set False to disable caching entirely

   provider_cache: dict[str, str] = {}   # {channel_user_id: "meta" | "twilio"}
   _PROVIDER_CACHE_MAX: int = 100

   def _remember_provider(channel_user_id: str, provider: str) -> None:
       if len(provider_cache) >= _PROVIDER_CACHE_MAX:
           provider_cache.pop(next(iter(provider_cache)))  # FIFO: drop oldest
       provider_cache[channel_user_id] = provider
   ```

   `send()` dispatch logic:
   - If `USE_PROVIDER_CACHE is True` and `reply.channel_user_id` is in
     `provider_cache`, dispatch directly via that cached provider — skip
     straight to building that provider's payload and sending, do not
     attempt the other provider first.
   - Otherwise (cache disabled, or no entry for this contact — covers a
     brand-new contact who has never messaged in, or any contact after a
     server restart since this is an in-memory dict that is not persisted
     to disk): **try Meta first.**
     - Meta succeeds → done. If `USE_PROVIDER_CACHE`, call
       `_remember_provider(reply.channel_user_id, "meta")`.
     - Meta returns **specifically error code 131030**
       (`"Recipient phone number not in allowed list"`) — check the `code`
       field exactly, not the message string, since wording can vary — then
       **retry via Twilio**. If that succeeds and `USE_PROVIDER_CACHE`, call
       `_remember_provider(reply.channel_user_id, "twilio")`.
     - **Any other error must propagate as-is and must not trigger a Twilio
       retry.** This specifically includes: 429 rate limit (already-required
       behaviour — do not change), auth/token errors, error 131047 (24-hour
       re-engagement window), and any timeout or 5xx/network error. Retrying
       on an ambiguous failure risks a real double-send if the original
       attempt actually succeeded and only the response read failed.

2. **Outbound authorization guard — do not skip:**
   ```python
   rec = get_pairing_store().lookup("whatsapp", reply.channel_user_id)
   if rec is None:
       return {"error": "recipient not paired", "code": "outbound_blocked"}
   ```
   This exists because nothing in the shared gateway code validates
   `send()`'s recipient — see §2.6. A deterministic check outside agent
   reasoning: holds even if the agent's decision was manipulated (e.g. by
   a prompt injection) into targeting the wrong number.
   **Team decision needed:** restrict to `owner_paired` only, or allow any
   paired contact? Document the choice in `US-14`.
3. Dispatch to `build_meta_send_payload`/Graph API or
   `build_twilio_send_payload`/Twilio's `Messages.json` based on the
   provider resolved in step 1.
4. Propagate 429s as-is, for either provider — don't raise, don't swallow.
5. *(Recommended)* `audit.append(..., event_type="outbound_reply", ...)`
   after a successful dispatch — see §0.3 for why the gateway doesn't do
   this for you.

**README note for US-14:** with the cache active, a contact registered on
both Meta and Twilio receives replies via whichever provider they most
recently messaged from, since `on_message` (US-9 step 3) overwrites the
cache entry on every verified inbound message. The Meta-first-with-131030-
fallback path only applies when there is no cache entry to consult — true
for a brand-new contact who has never messaged in, or for any contact
immediately after a server restart.

**Acceptance criteria:** `test_send_emits_valid_wire_payload` and
`test_rate_limit_propagates_429` still pass with the guard added —
confirmed safe, both use the `pair_owner` fixture which registers
`OWNER_ID` before calling `send()`.
**Exit criteria / commit:** merged; README states the pairing-tier decision.

### §7.11 US-11 — Twilio safety-net test suite (Option A)
**File:** `glc/channels/catalogue/whatsapp/tests/test_twilio_path.py` —
**inside our owned path**, merges exactly like `adapter.py`, no special
process (see §0.1, §5.1).
**Why this story exists:** the fixed suite structurally cannot exercise
Twilio at all (§0.1). Without this, Twilio has *zero* automated regression
protection. This closes that gap with a self-authored equivalent.
**Do, in two phases:**
- *Phase 1 (as soon as `US-6`/`US-7`/`US-8` exist, doesn't wait for Wave 2):*
  unit tests against each helper in isolation — a correctly-signed sample
  vs. a tampered one for `US-6`; a sample payload extraction for `US-7`;
  the exact form-body shape for `US-8`.
- *Phase 2 (once `US-9`/`US-10` land):* orchestrator-level tests mirroring
  the fixed suite's own shape — a Twilio "owner" case, a Twilio "stranger"
  case, an outbound payload-shape check, a signature-verification check
  using Twilio's real scheme.
**Acceptance criteria:** this suite gives Twilio the same *kind* of
regression coverage Meta gets from the fixed suite, even though it isn't
course-graded.
**Exit criteria / commit:** test file merged inside owned path; `US-12`'s
gate now requires it green alongside the 7 fixed Meta tests.

### §7.12 US-12 — QA / verification (one combined story, recurring + gate)
**Why one story, not two:** testing is part of building, not a phase
bolted on after — every Wave 1 story already self-verifies before its
mini-PR; the orchestrators get exercised against real suites the moment
they exist.

**Do — ongoing, from day one:** before merging any mini-PR:
```bash
ruff check glc/channels/catalogue/whatsapp/
mypy glc/channels/catalogue/whatsapp/
uv run python scripts/check_pr_boundaries.py --base main --head HEAD --group "Group WhatsApp"
```

**Do — the gate, once `US-9`, `US-10`, `US-11` are all merged:**
```bash
pytest tests/channels/test_whatsapp.py -v
pytest glc/channels/catalogue/whatsapp/tests/test_twilio_path.py -v
```
**Both suites green is the explicit go/no-go checkpoint** before `US-13`.
Not "manual verification" anymore — an actual automated check, on both
providers.
**Acceptance criteria:** both suites green; `ruff`/`mypy` clean; boundary
check passes.
**Exit criteria:** team proceeds to `US-13`. (Opening the actual final PR
and the full `scorecard.py` self-check is `US-15` — kept separate, since
PR-template-completeness needs a real draft PR body to evaluate against.)

### §7.13 US-13 — Demo recording (both providers)
**Depends on:** `US-12` green, `US-1`, `US-2`.
**Do:** Record real end-to-end passes for **both** providers — a Meta
message and a Twilio sandbox message, each arriving → `on_message` →
(agent stub/echo) → `send()` → reply visible on the real phone. Terminal/
log output visible as the chat-trace overlay for both.
**Acceptance criteria:** video clearly shows two real round-trips, tagged
by provider, not just the pytest suite running.
**Exit criteria / commit:** video uploaded; link handed to `US-14`/`US-15`.

### §7.14 US-14 — README.md
**Branch:** `feature/us14-readme`
**Depends on:** `US-13` (describes the real demo and quirks actually hit).
**Do:** Architecture summary (paste the Mermaid diagram), channel quirks
(24-hour window — Meta error `131047`, Twilio error `63016`; `hub.challenge`
handshake; neither provider supports WhatsApp groups or @mentions), full
Meta setup (§8), full Twilio setup (§9), exact env vars for both
providers (including `TWILIO_WEBHOOK_URL` from `US-6`'s gotcha), which
pairing tier (`US-10`'s decision) is allowed outbound sends, and an
explicit note that the Twilio test suite (`US-11`) is self-built, not
course-graded.
**Acceptance criteria:** a teammate with zero WhatsApp/Twilio experience
can follow only this README and get both providers round-tripping.
**Exit criteria / commit:** `README.md` merged.

### §7.15 US-15 — Final PR
**Depends on:** everything above.
**Do:**
1. Draft the PR body locally — `# Group:`/`# Slot:` markers (exact text,
   §10), the demo link, "members" with the team list, a "quirks"/"wire"
   paragraph covering both providers.
2. Self-check the rubric:
   ```bash
   uv run python scripts/scorecard.py --pr-body "$(cat draft_pr_body.txt)" --base main --head HEAD
   ```
3. Fix anything short of 10/10 that's fixable.
4. Open the PR per §10. **This PR ships Option A** — `US-11`'s Twilio test
   file stays inside our owned path. It does not attempt the move to
   Option B (backlog `B3`).
**Acceptance criteria:** local `scorecard.py` shows 10/10, or every
shortfall is understood and accepted deliberately.
**Exit criteria:** final PR opened, passing CI, demo and README in place.

### §7.16 Backlog — grab any time, never blocks US-1 through US-15

**B1 — `schemas.py` typed wrappers.**
*File:* `glc/channels/catalogue/whatsapp/schemas.py`.
*Do:* Pydantic models over `US-4`/`US-5`/`US-7`/`US-8`'s dict shapes,
calling `.model_dump()` before any value that must stay a plain dict for
the fixed test's assertions.
*Acceptance criteria:* all tests (fixed + `US-11`) still pass; `mypy` clean.
*Why optional:* pure style, zero functional or grading impact — the
course's own stub leaves it commented out.

**B2 — Gateway WebSocket glue.**
*File:* new `glc/channels/catalogue/whatsapp/ws_client.py`.
*Do:* `glc/routes/channels.py` shows adapters are meant to hold a live WS
connection to `/v1/channels/whatsapp` in production, round-tripping
through the gateway's own allowlist/rate-limit/audit pipeline. Not
exercised by any fixed test; `docs/ADAPTER_GUIDE.md` doesn't document it.
*Acceptance criteria:* if built, `US-13`'s demo can be re-recorded showing
the real gateway pipeline instead of direct-to-provider calls.
*Why optional:* `channels.py`'s own comment says the agent runtime is
still a stub for S11; not requested by the Admin.

**B3 — Move `US-11`'s Twilio test file to Option B.**
*Target:* `tests/channels/test_whatsapp_twilio.py` (mirroring where the
fixed Meta test lives).
*Do:* a **second, standalone PR**, scoped only to this file move, with
**no `# Group:` marker at all** (the boundary check's documented bypass
condition — see §0.1's exact quote from `GROUPS.md`), under
`@theschoolofai` review.
*Why optional, why sequenced after `US-15`:* this is an external,
uncontrolled-timing dependency (maintainer review) — exactly why it
doesn't belong in the main submission path. Only attempt once `US-11`
has proven stable in its Option A location and there's spare time after
`US-15`.

---

## §7.17 `help_docs/` folder organisation

Each user story that produces documentation, screenshots, or helper scripts
gets its own subfolder named `US<N>_<short_description>/`. Cross-story docs
stay at the root.

```
help_docs/
├── HANDOFF.md                          ← this file (master doc, root)
├── pick_my_task.md                     ← task navigation aid (root)
├── whatsapp_adapter_flow.mermaid       ← architecture diagram (root)
├── US1_meta_wiring/
│   ├── US1_meta_wiring_setup.md       ← step-by-step guide
│   ├── scripts/
│   │   ├── meta_webhook_test_server.py
│   │   └── meta_waba_subscribe_and_roundtrip.py
│   └── screenshots/
│       └── [01–13 pngs]
├── US2_twilio_wiring/                  ← created when US-2 is done
│   ├── US2_twilio_wiring_setup.md
│   └── screenshots/
└── ...                                 ← US3–15 folders as needed
```

**Rules:**
- All scripts use `pyproject.toml`-anchored root detection — they work
  regardless of where they sit in the tree. Run from the repo root:
  `uv run python glc/channels/catalogue/whatsapp/help_docs/US<N>_.../scripts/<script>.py`
- Screenshots always go under `<story-folder>/screenshots/` — no shared
  top-level `screenshots/` directory.
- Nothing in `help_docs/` is production code. Scripts here are setup/dev
  tools, committed for reproducibility, never imported by the adapter.

---

## §8. Meta WhatsApp Cloud API — full test-account setup

> ⚠️ **The Meta Developer UI changed significantly in 2025.** Steps 1–3 and 7 below
> describe the old UI and are no longer accurate. The authoritative, up-to-date
> step-by-step (reflecting the wizard-based 2026 UI, actually executed and
> verified on 23 Jun 2026) is in:
> `glc/channels/catalogue/whatsapp/help_docs/US1_meta_wiring/US1_meta_wiring_setup.md`
> Use that document instead of the steps below.

No business verification needed for any of this.

1. ~~**Meta for Developers → My Apps → Create App**, **Business** app type.~~
   *Replaced by wizard: App details → Use cases (select WhatsApp) → Business Portfolio → Overview → Create app. See §8 help doc.*
2. ~~**Add Product → WhatsApp** → **Getting Started**~~ — *There is no "Add a Product" button in the new UI. Use cases → Customize → Continue → Step 1. Try it out.*
3. **"Step 1. Try it out"** panel (previously called "API Setup") → **Generate access token** (temporary, 24h).
4. Pick the **From** test number, add a **To** number (your phone), send
   the pre-filled `hello_world` template to verify the basic path.
5. Note the test phone number ID and WhatsApp Business Account ID.
6. Reply from your phone — opens the 24-hour customer service window.
7. **60-day token (replaces System Users approach):** Go to
   [developers.facebook.com/tools/explorer](https://developers.facebook.com/tools/explorer),
   select your app, add `whatsapp_business_management` + `whatsapp_business_messaging`
   permissions, click **Generate Access Token**, then exchange the short-lived token
   for a 60-day one via the Graph API. See Step 10 in the help doc.
   *(System Users requires a Facebook Page — it was blocked in this setup. Graph API
   Explorer works with an unverified Business Portfolio.)*
8. **App Secret:** **App Settings → Basic → App secret → Show.** This is
   `WHATSAPP_APP_SECRET`.
9. **Webhook:** expose your local server with `ngrok http 8765` (or
   `cloudflared`). **WhatsApp → Configuration → Edit**,
   enter the Callback URL and a Verify Token, **Verify and Save**. Meta
   sends a one-time GET with `hub.mode`/`hub.verify_token`/`hub.challenge`
   — echo `hub.challenge` back as plain text with 200 once the token matches.
10. Subscribe to the **messages** webhook field by running:
    `uv run python glc/channels/catalogue/whatsapp/help_docs/US1_meta_wiring/scripts/meta_waba_subscribe_and_roundtrip.py <your-number>`
    (see Phase B in the help doc).

**Required `.env` values:** `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN`,
`WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_WABA_ID`, `WHATSAPP_APP_ID`.
See `.env.example` for the full template.

---

## §9. Twilio WhatsApp Sandbox — full setup

No WhatsApp Business Account needed.

1. Sign up at twilio.com, verify email/phone.
2. Console → note **Account SID** and **Auth Token**.
3. **Messaging → Try it out → Send a WhatsApp message**, activate Sandbox
   (shared number, commonly `+1 415 523 8886`).
4. Each test recipient sends `join <sandbox-code>` to that number (3-day
   expiry — rejoin if testing spans longer).
5. **Sandbox Settings → Sandbox configuration** → set the "When a message
   comes in" webhook URL to your tunnel — Twilio POSTs form-urlencoded
   data, signed with `X-Twilio-Signature` (see `US-6` for the exact scheme
   and the full-URL requirement).
6. Send: `POST https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json`,
   Basic Auth with SID/Auth Token.
7. Outside the 24-hour window, only pre-approved templates send — a
   free-form send returns Twilio error **63016**.

**Required `.env` values:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, the
sandbox number, and `TWILIO_WEBHOOK_URL` (the exact public URL configured
in step 5 — needed by `US-6`'s signature check).

---

## §10. Final PR — exact submission checklist

Detailed procedure `US-15` points to.

1. Confirm `integration` has `US-1` through `US-14` done, `US-12`'s gate
   passing on both suites.
2. Open PR: base `theschoolofai/glc_v1:main` ← compare
   `rraghu214/glc_v1_whatsapp:integration`.
3. PR description, own lines:
   ```
   # Group: Group WhatsApp
   # Slot: whatsapp
   ```
   (Match `GROUPS.md`'s exact text — the normalizer strips a `"group "`
   prefix with a space, not a hyphen, so the LMS's hyphenated
   `group-whatsapp` marker risks not matching.)
4. Fill PR template fields; re-run `scorecard.py` against this exact body.
5. Add the demo link (`US-13`).
6. Wait for CI and CODEOWNERS review.
7. On merge: the fork owner pastes fork URL, PR URL, demo URL into the LMS.

---

## §11. Target internal timeline

Official deadlines: Implementation PR Jul 1, demo Jul 2, review through
Jul 5 (Jul 6 banner unconfirmed — §0.2).

| By | Target |
|---|---|
| Day 1 | All 8 Wave 1 stories (`US-1`–`US-8`) started in parallel |
| Day 1–2 | Wave 1 merged and individually verified |
| Day 2–3 | `US-9`, `US-10` merged; `US-11` Phase 1 underway |
| Day 3–4 | `US-11` Phase 2 complete; `US-12`'s gate green on both suites |
| Day 4 | `US-13` demo recorded (both providers) |
| Day 4–5 | `US-14` README finalized; `US-15` final PR opened |

Leaves several days of buffer before Jul 1 even at a relaxed pace.
