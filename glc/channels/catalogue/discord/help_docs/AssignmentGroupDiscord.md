Group Discord



Session 11 — GLC v1: Build a Gateway Adapter (team assignment)
If you are NOT in any group, then email admin@theschoolofai.in

If you submit assuming you are done, but your code is NOT user friendly and is not usable (easy to integrate) then it will be rejected.

Repo: theschoolofai/glc_v1 (public, MIT, Python 3.11 + FastAPI)

This is a team assignment. The cohort is building 22 adapter slots of the GLC v1 gateway: 15 channel adapters (Telegram, Discord, WhatsApp, ...) and 7 voice providers (Groq Whisper, ElevenLabs, Kokoro, ...). Each team owns one slot end to end.

Your group name (in the LMS) is the slot you're working on. Find your slot in the table below.

Workflow
Fork the repo. The team lead opens github.com/theschoolofai/glc_v1 → Fork, then shares the fork URL with the team. Save it in the Fork URL field on this page.
Claim PR (workflow-learning step, due 2026-06-23 23:59 IST). One PR per team that edits CLAIMS.md: replace (unclaimed) in your slot's row with your group marker (see "PR markers" below). Title: claim: <slot> for <group-marker>. Use ?template=claim.md.
Implementation PR (due 2026-07-01 23:59 IST). Implement adapter.py against the 7 tests in your slot's test file. The default PR template embeds the two required markers (see below).
Demo video (due 2026-07-02 23:59 IST). YouTube or Loom link, included in the implementation PR body. Must show your adapter handling a real upstream message end to end, not just the mock. (The CI tests run against the mock; the demo is how you prove the real wire path works.)
Review window: 2026-07-03 → 2026-07-05. Grader merges PRs and posts the scorecard.
Source of truth: docs/ADAPTER_GUIDE.md in the repo. If anything here contradicts the guide, the guide wins.

PR markers (this is what CI matches)
Both markers go on their own line in the PR body (not the title). Case-insensitive, leading whitespace allowed. Trailing text on the line breaks the match.

# Group: group-2-discord
# Slot: <slot-key-with-underscores>
Example for Group Gmail:

# Group: group-gmail
# Slot: gmail
Slot keys use underscores (e.g. twilio_sms, gemini_live_stt). Group markers use hyphens (e.g. group-twilio-sms, group-gemini-live-stt). The "Group" column below shows the exact marker for every team.

Boilerplate code: D:\sjk\eagv3\011_session\glc_v1\glc\channels\catalogue\discord


Test mock: D:\sjk\eagv3\011_session\glc_v1\tests\channels\test_discord.py

D:\sjk\eagv3\011_session\glc_v1\tests\channels\test_discord.py


Rubric (2000 points, auto-scored by CI scorecard scaled ×200)
Item	Points
6 structural tests pass (200 pts each)	1200
1 behavioural test passes	400
ruff clean on your owned path	100
mypy clean on your owned path	100
PR template completeness (group / slot / members / demo / quirks)	100
Adapter discipline (no LangChain / CrewAI / AutoGen; trust-level called for channels)	100
Total	2000
The CI scorecard posts a comment on your PR with the breakdown out of 10. The grader scales Total /10 ×200 to land your gradebook score out of 2000.

Behavioural test caveat (important). The 7 CI tests run against a mock, not a real upstream. The mock emits real wire-format payloads (real Telegram Updates, real Discord MESSAGE_CREATE, real WhatsApp HMAC-signed bodies, etc.), so passing the tests proves you understood the wire format. But passing all 7 does not prove the real call works. The demo video is how you prove the real wire path — adapters with placeholder upstream calls will pass CI and still lose the 2 behavioural points if the demo isn't real.

Voice provider signups (free tiers)
Slot	Sign up
groq_whisper	console.groq.com → API keys → GROQ_API_KEY
elevenlabs	elevenlabs.io → 10k chars/month free → ELEVENLABS_API_KEY
cartesia	play.cartesia.ai → Dashboard → CARTESIA_API_KEY
gemini_live_stt and gemini_live_tts	aistudio.google.com → Get API key → GEMINI_API_KEY (one key covers both)
whisper_cpp	No signup. Build from github.com/ggerganov/whisper.cpp; model file downloaded locally.
kokoro	No signup. Local Kokoro-82M pipeline.
Deeper reference: docs/VOICE_GUIDE.md.

What you submit on this page
Three artifacts. None of them are scored on this page (grading happens off the CI scorecard). They're for the grader to find your work:

Fork URL — the team's fork of glc_v1 (also save it on the team in the Repo URL field).
Implementation PR URL — the PR that adds your adapter implementation.
Demo video URL — YouTube / Loom / Vimeo link showing the real upstream call.
Deadlines (IST)
When
Claim PR	Tue 2026-06-23 23:59
Implementation PR	Wed 2026-07-01 23:59
Demo video link in PR	Thu 2026-07-02 23:59
Review + scorecard	Fri 2026-07-03 → Sun 2026-07-05
Late policy: submissions accepted until the review window closes (2026-07-05). Resubmissions allowed.