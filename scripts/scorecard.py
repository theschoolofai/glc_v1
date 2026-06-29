"""Per-group scorecard.

Run for an open implementation PR. Computes a rubric-based score and
emits a Markdown comment body suitable for `gh pr comment --body-file`.

Rubric (10 points):
  - 6 structural tests pass:                6 pts (1 each)
  - 1 behavioural test passes:              2 pts
  - ruff clean on owned paths:              0.5 pt
  - mypy clean on owned paths:              0.5 pt
  - PR template completeness:               0.5 pt
  - Adapter-discipline checks:              0.5 pt
                                       ────
                                       10 pts

CI usage:
  uv run python scripts/scorecard.py \\
      --pr-body "$PR_BODY" --pr-number "$PR_NUMBER" \\
      --base "$BASE" --head "$HEAD" \\
      > scorecard.md
  gh pr comment "$PR_NUMBER" --body-file scorecard.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GROUP_MARKER_RE = re.compile(r"^\s*#\s*Group:\s*([^\r\n]+?)\s*$", re.IGNORECASE | re.MULTILINE)
SLOT_MARKER_RE = re.compile(r"^\s*#\s*Slot:\s*([\w-]+)\s*$", re.IGNORECASE | re.MULTILINE)
DEMO_RE = re.compile(r"(youtube\.com|youtu\.be|loom\.com|vimeo\.com)", re.IGNORECASE)


def _slot_to_test_paths(slot: str) -> tuple[str | None, str | None]:
    """Returns (test_file_path, adapter_dir_path) or (None, None)."""
    candidates: list[tuple[Path, Path]] = [
        (ROOT / "tests/channels" / f"test_{slot}.py", ROOT / "glc/channels/catalogue" / slot),
        (ROOT / "tests/voice/stt" / f"test_{slot}.py", ROOT / "glc/voice/stt/providers" / slot),
        (ROOT / "tests/voice/tts" / f"test_{slot}.py", ROOT / "glc/voice/tts/providers" / slot),
    ]
    for test_path, adapter_dir in candidates:
        if test_path.exists():
            return str(test_path.relative_to(ROOT)), str(adapter_dir.relative_to(ROOT))
    return None, None


def _run(cmd: list[str]) -> tuple[int, str]:
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    return out.returncode, (out.stdout + "\n" + out.stderr).strip()


def _pytest_report(test_path: str) -> dict[str, list[str]]:
    """Returns {'passed': [...], 'failed': [...]}."""
    rc, output = _run(
        ["uv", "run", "pytest", test_path, "-v", "--tb=no", "--no-header"],
    )
    passed: list[str] = []
    failed: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if " PASSED" in line:
            passed.append(line.split(" PASSED")[0].strip())
        elif " FAILED" in line:
            failed.append(line.split(" FAILED")[0].strip())
    return {"passed": passed, "failed": failed}


def _ruff_clean(adapter_dir: str) -> bool:
    rc, _ = _run(["uv", "run", "ruff", "check", adapter_dir])
    return rc == 0


def _mypy_clean(adapter_dir: str) -> bool:
    rc, _ = _run(["uv", "run", "mypy", adapter_dir])
    return rc == 0


def _pr_template_score(pr_body: str) -> tuple[float, list[str]]:
    """Returns (score 0–0.5, list of missing fields)."""
    missing: list[str] = []
    if not GROUP_MARKER_RE.search(pr_body):
        missing.append("`# Group: <name>` marker")
    if not DEMO_RE.search(pr_body):
        missing.append("demo video link (YouTube/Loom/Vimeo)")
    if "quirks" not in pr_body.lower() and "wire" not in pr_body.lower():
        missing.append("wire-format quirks paragraph")
    if "members" not in pr_body.lower():
        missing.append("group members list")
    score = 0.5 * max(0.0, 1.0 - len(missing) / 4)
    return round(score, 2), missing


def _discipline_score(adapter_dir: str) -> tuple[float, list[str]]:
    """Heuristic adapter-discipline checks against the owned source dir."""
    notes: list[str] = []
    score = 0.5
    src_files = list((ROOT / adapter_dir).rglob("*.py"))
    src = "\n".join(p.read_text() for p in src_files if p.is_file())
    forbidden = ["langchain", "crewai", "autogen", "open_interpreter"]
    for f in forbidden:
        if f in src.lower():
            notes.append(f"forbidden import: {f}")
            score -= 0.25
    if "trust_level" not in src and "classify" not in src and "voice/" not in adapter_dir:
        notes.append("missing trust-level classification")
        score -= 0.25
    return round(max(0.0, score), 2), notes


def build_scorecard(*, pr_body: str, base: str, head: str, pr_number: str | None = None) -> str:
    group_m = GROUP_MARKER_RE.search(pr_body)
    slot_m = SLOT_MARKER_RE.search(pr_body)
    group = group_m.group(1) if group_m else "(unknown group)"
    slot = slot_m.group(1) if slot_m else None

    lines: list[str] = ["## GLC scorecard", ""]
    lines.append(
        f"**Group**: `{group}`  ·  **Slot**: `{slot or '(unknown)'}`  ·  **PR**: #{pr_number or '?'}"
    )
    lines.append("")

    if slot is None:
        lines.append("No `# Slot: <name>` marker in PR description — scorecard skipped.")
        return "\n".join(lines)

    test_path, adapter_dir = _slot_to_test_paths(slot)
    if test_path is None:
        lines.append(f"Unknown slot `{slot}` — no matching test file or adapter dir.")
        return "\n".join(lines)

    report = _pytest_report(test_path)
    structural = [
        t
        for t in report["passed"] + report["failed"]
        if not t.endswith("channel_specific_behaviour") and "behaviour" not in t
    ]
    behavioural = [t for t in report["passed"] + report["failed"] if "behaviour" in t]

    s_passed = [t for t in structural if t in report["passed"]]
    s_failed = [t for t in structural if t in report["failed"]]
    b_passed = [t for t in behavioural if t in report["passed"]]
    b_failed = [t for t in behavioural if t in report["failed"]]

    structural_pts = min(6, len(s_passed))
    behavioural_pts = 2 if b_passed and not b_failed else 0

    ruff_ok = _ruff_clean(adapter_dir)
    mypy_ok = _mypy_clean(adapter_dir)
    template_pts, template_missing = _pr_template_score(pr_body)
    discipline_pts, discipline_notes = _discipline_score(adapter_dir)

    total = round(
        structural_pts
        + behavioural_pts
        + (0.5 if ruff_ok else 0)
        + (0.5 if mypy_ok else 0)
        + template_pts
        + discipline_pts,
        2,
    )

    def tick(ok: bool) -> str:
        return "✓" if ok else "✗"

    lines.extend(
        [
            "| Item                                | Result | Points |",
            "|-------------------------------------|--------|--------|",
            f"| Structural tests ({len(s_passed)}/{len(structural)})   | {tick(not s_failed)}      | {structural_pts}/6   |",
            f"| Behavioural test                    | {tick(bool(b_passed) and not b_failed)}      | {behavioural_pts}/2     |",
            f"| `ruff check {adapter_dir}`          | {tick(ruff_ok)}      | {0.5 if ruff_ok else 0}/0.5 |",
            f"| `mypy {adapter_dir}`                | {tick(mypy_ok)}      | {0.5 if mypy_ok else 0}/0.5 |",
            f"| PR template completeness            | {tick(not template_missing)}      | {template_pts}/0.5  |",
            f"| Adapter discipline                  | {tick(not discipline_notes)}      | {discipline_pts}/0.5  |",
            f"| **Total**                           |        | **{total}/10** |",
            "",
        ]
    )

    if s_failed:
        lines.append("### Failing structural tests")
        for t in s_failed:
            lines.append(f"- `{t}`")
        lines.append("")
    if b_failed:
        lines.append("### Failing behavioural test")
        for t in b_failed:
            lines.append(f"- `{t}`")
        lines.append("")
    if template_missing:
        lines.append("### PR template gaps")
        for m in template_missing:
            lines.append(f"- {m}")
        lines.append("")
    if discipline_notes:
        lines.append("### Adapter-discipline notes")
        for n in discipline_notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("---")
    lines.append(f"_Scorecard generated by `scripts/scorecard.py`. Diff range: `{base}..{head}`._")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr-body", required=True)
    ap.add_argument("--pr-number", default=None)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()
    print(
        build_scorecard(
            pr_body=args.pr_body,
            base=args.base,
            head=args.head,
            pr_number=args.pr_number,
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
