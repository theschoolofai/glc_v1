# Implementation Plan for Discord Gateway Adapter (group-2-discord)

This plan details the steps required to claim, implement, verify, and submit the Discord Gateway Adapter for **Session 11 — GLC v1**.

---

## 1. Environment Setup & Branching
- [ ] Create and check out a dedicated local implementation branch:
  ```powershell
  git switch -c glc_v1_g2_discord_impl
  ```
- [ ] Ensure python 3.11 is available and dependencies are installed using `uv`:
  ```powershell
  uv sync
  ```
- [ ] Verify that you can run the test suite (it should fail initially because the adapter throws `NotImplementedError`):
  ```powershell
  uv run pytest tests/channels/test_discord.py -v
  ```

---

## 2. Claim the Slot (Deadline: Tue 2026-06-23 23:59 IST)
- [ ] Edit `CLAIMS.md` in the root of the repository.
- [ ] Find the row corresponding to the `discord` slot and replace `(unclaimed)` with your group marker `group-2-discord`.
- [ ] Commit this change and push the branch to your fork.
- [ ] Open a Pull Request targeting `theschoolofai/glc_v1:main`:
  - **PR Title**: `claim: discord for group-2-discord`
  - **PR Template**: Use `?template=claim.md` if available.

---

## 3. Implement the Adapter (Deadline: Wed 2026-07-01 23:59 IST)
You will edit [adapter.py](file:///d:/sjk/eagv3/011_session/glc_v1/glc/channels/catalogue/discord/adapter.py) to implement the required interface against the mock definitions in [discord_mock.py](file:///d:/sjk/eagv3/011_session/glc_v1/tests/channels/mocks/discord_mock.py).

### Tasks:
- [ ] **Handle Disconnects**:
  - In `on_message`, check if a mock is configured (`self.config.get("mock")`).
  - Check if there is a pending disconnect by calling `mock.pop_disconnect()`.
  - If a disconnect is pending, return a reconnect envelope cleanly (do **not** raise an exception).
- [ ] **Parse Inbound Messages**:
  - Extract the raw Discord gateway payload structure (e.g., matching the `MESSAGE_CREATE` event payload: author's ID, content, timestamp, and metadata).
  - Wrap it into a `ChannelMessage` envelope with `channel="discord"`.
- [ ] **Classify Trust Levels**:
  - Use `classify()` / `trust_level.classify()` to determine if the message is from a paired owner or a stranger.
  - Implement allowlist enforcement in public channels (`config["is_public_channel"] = True`) to drop messages from strangers or classify them as untrusted.
- [ ] **Mention Resolution (Behavioural Rubric)**:
  - Search message content for user mentions formatted as `<@user_id>`.
  - Resolve the user information using `mock.get_user(user_id)`.
  - Append the resolved username/handle to `ChannelMessage.metadata["mentions"]`.
- [ ] **Implement Outbound Sends**:
  - Construct the Discord REST API payload (must contain the `content` key; do not include `tts: true` by default).
  - Dispatch the payload to `mock.send(...)` if in mock mode, or make the actual network request to Discord.
- [ ] **Propagate Rate Limits (429)**:
  - Ensure rate limits from upstream are propagated properly as a structured dictionary containing `status: 429` or `retry_after`.

---

## 4. Verification & Quality Gates
- [ ] Run the automated unit test suite locally to verify all 7 tests pass:
  ```powershell
  uv run pytest tests/channels/test_discord.py -v
  ```
- [ ] Run code formatters and linters on the Discord code:
  ```powershell
  uv run ruff check glc/channels/catalogue/discord/
  ```
- [ ] Run static type checking on the Discord code:
  ```powershell
  uv run mypy glc/channels/catalogue/discord/
  ```

---

## 5. Submission (Deadline: Wed 2026-07-01 23:59 IST)
- [ ] Push the completed implementation branch to your GitHub fork:
  ```powershell
  git push origin glc_v1_g2_discord_impl
  ```
- [ ] Open the Implementation PR targeting the upstream `main` branch.
- [ ] **Critical:** Ensure the PR body contains the required template markers on their own lines:
  ```text
  # Group: group-2-discord
  # Slot: discord
  ```
- [ ] Record a demo video (using YouTube, Loom, or Vimeo) showing the adapter handling a real upstream Discord message (not just the mock) end-to-end.
- [ ] Update the PR description to include the **Demo Video URL** before the deadline (Thu 2026-07-02 23:59 IST).
