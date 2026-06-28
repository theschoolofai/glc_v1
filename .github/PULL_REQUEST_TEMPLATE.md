# Implementation PR

<!--
  KEEP the two markers below intact. The boundary check (which paths
  you can touch) and the scorecard bot (the comment you'll see on this
  PR) both read these lines. Don't remove the leading `#`.
-->

# Group: Webhook
# Slot: webhook

<!--
  Use the short form for the group name — i.e. `Telegram`, `Whisper.cpp`,
  `Gemini Live STT` — not `Group Telegram`. The slot is the lowercase
  identifier from the table in GROUPS.md, e.g. `telegram`, `whisper_cpp`,
  `gemini_live_stt`.
-->

## Group

- Tanmay Sharma @tanmays369
- Ashwani Bindroo @AshwaniBindroo-TomTom
- Bhuvaneshwari R @Bhuvanaa28
- Naren V @vnaren13


## What this PR adds

For a channel slot:

- [ ] `glc/channels/catalogue/webhook/adapter.py` — `on_message` + `send`
- [ ] `glc/channels/catalogue/webhook/schemas.py` — channel-specific types (if any)
- [ ] All 7 tests at `tests/channels/test_webhook.py` pass


## Demo

<!-- REQUIRED. Link to the YouTube/Loom/Vimeo demo showing your
     adapter handling a real upstream message end to end (NOT just the
     mock). The CI tests run against the mock; the demo is how you
     prove the real wire path works. -->

## Wire-format quirks you hit

<!-- 2-4 sentences. What was surprising about this slot's wire format,
     auth model, rate-limit behaviour, or trust posture? -->

## Tests-included checklist

- [ ] All 7 tests in `tests/.../test_<slot>.py` pass locally
- [ ] `ruff check <owned_path>` is clean
- [ ] `mypy <owned_path>` is clean
- [ ] Adapter does **not** hold long-lived credentials in code or env files
- [ ] For channel slots: adapter consults `glc.security.trust_level.classify()` before constructing the envelope
- [ ] For channel slots: adapter respects the channel's `allowed_senders` setting
- [ ] No imports from LangChain, CrewAI, AutoGen, or Open Interpreter

## Notes for the reviewer

<!-- Anything the reviewer should know before merge. -->
