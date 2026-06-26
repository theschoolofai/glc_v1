# Project conventions for Claude Code sessions

When you create git commits in this repository:

- **Do NOT include a `Co-Authored-By: Claude ...` trailer.**
  The maintainer prefers commits to show a single human author. The
  default Claude Code commit recipe adds this trailer; override it
  for this repo.

- Commit messages should be terse and focused. Subject line under 70
  chars, optional body explaining the *why*, no AI-tooling
  attribution.

- Never push directly to `main` from a Claude session unless the
  maintainer has explicitly asked for it in the current turn.
  Branch + PR is the default path.

These rules apply to every Claude session that operates on this
repository, regardless of the channel they were invoked through.
