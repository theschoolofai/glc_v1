# Implementation PR

> [!IMPORTANT]
> **Edit the two `# Group:` and `# Slot:` lines below before pushing.** The boundary check reads them literally.
>
> - **Group**: the name as it appears in [`GROUPS.md`](../blob/main/GROUPS.md), e.g. `Telegram`, `Whisper.cpp`, `Gemini Live STT`.
>   Do **not** use `group-telegram`, `group-whisper-cpp`, or any other variation.
> - **Slot**: the lowercase identifier from the same row, e.g. `telegram`, `whisper_cpp`, `gemini_live_stt`.

# Group: EDIT_ME_GROUP_NAME
# Slot: EDIT_ME_SLOT

## Group

- **Members**: <!-- one line per member -->

## What this PR adds

For a channel slot:

- [ ] `glc/channels/catalogue/<slot>/adapter.py` — `on_message` + `send`
- [ ] `glc/channels/catalogue/<slot>/schemas.py` — channel-specific types (if any)
- [ ] All 7 tests at `tests/channels/test_<slot>.py` pass

For a voice provider slot:

- [ ] `glc/voice/{stt,tts}/providers/<slot>/adapter.py` — `transcribe` or `synthesize`
- [ ] `glc/voice/{stt,tts}/providers/<slot>/schemas.py` — provider-specific types (if any)
- [ ] All 7 tests at `tests/voice/{stt,tts}/test_<slot>.py` pass

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
