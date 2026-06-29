"""Boundary check.

Reads `GROUPS.md` plus the PR's `# Group: <name>` marker and the
git-diff against the merge base. Fails if the PR touches files
outside the owned paths of the group's claimed slot.

CI usage:
  uv run python scripts/check_pr_boundaries.py \\
      --base "$GITHUB_BASE_SHA" \\
      --head "$GITHUB_HEAD_SHA" \\
      --pr-body "$PR_BODY"

Local usage (during development, against your working tree):
  uv run python scripts/check_pr_boundaries.py \\
      --base main --head HEAD --group <your-group>

Behaviour
---------
- Reads each `(channel|provider, group, owned-paths)` row from GROUPS.md.
- Locates the group's claimed slots (a group may claim more than one
  slot in principle; the script unions their paths).
- For each file in `git diff --name-only base..head`, checks the path
  against the union of owned globs.
- Fails if any file is outside the union.

The script also recognises two allowlist categories that any group
may touch:
  - `GROUPS.md` (to update the claim row itself)
  - PR-meta files: `.github/PULL_REQUEST_TEMPLATE.md`
The maintainers' shared-code path bypasses the check by omitting the
`# Group:` marker — the script exits 0 in that case with a notice.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAIMS_PATH = ROOT / "GROUPS.md"

# Any group may modify these without a slot claim.
SHARED_ALLOWLIST: list[str] = [
    "GROUPS.md",
]


ROW_RE = re.compile(r"^\|\s*([\w-]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$")
# Group marker accepts any name to the end of the line, so students can
# write "Telegram", "Group Telegram", or "Whisper.cpp" — we normalise both
# sides before comparing in `claimed_globs`.
GROUP_MARKER_RE = re.compile(r"^\s*#\s*Group:\s*([^\r\n]+?)\s*$", re.IGNORECASE | re.MULTILINE)


def normalize_group(name: str) -> str:
    """`Group Telegram` and `Telegram` both normalise to `telegram`."""
    n = name.strip().lower()
    if n.startswith("group "):
        n = n[len("group ") :].strip()
    return n


PLACEHOLDER_VALUES = {
    "edit_me_group_name",
    "<your-group-name>",
    "<group-name>",
    "<replace-me>",
    "your-group-name",
}


def suggest_group_fix(group: str, rows: list[tuple[str, str, list[str]]]) -> str:
    """Return a one-line hint for an unrecognised group value."""
    lowered = group.strip().lower()
    valid = sorted({g for _s, g, _gl in rows})

    # 1) Student left the PR-template placeholder in.
    if "<" in group or lowered in PLACEHOLDER_VALUES or "edit_me" in lowered:
        return (
            "you left the PR-template placeholder in. Edit the `# Group:` and "
            "`# Slot:` lines in the PR description to match your row in GROUPS.md."
        )

    # 2) Common bug: `group-X` with a hyphen instead of `X`.
    if lowered.startswith("group-"):
        rest = group[len("group-") :].replace("-", " ").replace("_", " ").strip()
        target = rest.lower()
        for v in valid:
            if normalize_group(v) == target:
                return (
                    f"did you mean `# Group: {v}`? GROUPS.md uses the plain name without the `group-` prefix."
                )
        return (
            "GROUPS.md uses the plain name without the `group-` prefix. "
            f"Try `# Group: {rest.title()}` (one of: {', '.join(valid)})."
        )

    # 3) Anything else — list the valid names so the student can pick.
    return f"valid `# Group:` values from GROUPS.md: {', '.join(valid)}"


def parse_claims(text: str) -> list[tuple[str, str, list[str]]]:
    """Returns [(slot, group, [owned_globs])] for non-header, non-divider rows."""
    rows: list[tuple[str, str, list[str]]] = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        slot, group, paths = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        # Skip header and divider rows.
        if slot.lower() == "slot" or set(slot) <= {"-"}:
            continue
        if group.startswith("---") or paths.startswith("---"):
            continue
        # `Owned paths` is a space-separated list of backtick-quoted globs.
        globs = re.findall(r"`([^`]+)`", paths)
        if not globs:
            continue
        rows.append((slot, group, globs))
    return rows


def claimed_globs(rows: list[tuple[str, str, list[str]]], group: str) -> list[str]:
    target = normalize_group(group)
    out: list[str] = []
    for _slot, g, globs in rows:
        if normalize_group(g) == target:
            out.extend(globs)
    return out


def matches_any(path: str, globs: list[str]) -> bool:
    for g in globs:
        # Recursive glob support: a/** matches anything under a/.
        if g.endswith("/**"):
            prefix = g[:-3]
            if path == prefix.rstrip("/") or path.startswith(prefix):
                return True
        if fnmatch.fnmatch(path, g):
            return True
    return False


def git_diff_names(base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument(
        "--group",
        default=None,
        help="override the group name (otherwise read from --pr-body)",
    )
    ap.add_argument(
        "--pr-body",
        default="",
        help="PR description text; scanned for the `# Group: <name>` marker",
    )
    args = ap.parse_args()

    group = args.group
    if not group:
        m = GROUP_MARKER_RE.search(args.pr_body)
        if m:
            group = m.group(1).strip()

    rows = parse_claims(CLAIMS_PATH.read_text())
    if not group:
        # Shared-code PR — no group marker. Exit clean; CODEOWNERS will
        # require a maintainer review.
        print("[boundary] no `# Group: <name>` marker; treating as shared-code PR")
        return 0

    globs = claimed_globs(rows, group)
    if not globs:
        print(f"[boundary] FAIL: group {group!r} has no claimed slot in GROUPS.md")
        print(f"[boundary] hint: {suggest_group_fix(group, rows)}")
        return 2

    files = git_diff_names(args.base, args.head)
    stray = [f for f in files if not matches_any(f, globs + SHARED_ALLOWLIST)]
    if stray:
        print(f"[boundary] FAIL: group {group!r} touched files outside its owned paths:")
        for f in stray:
            print(f"  - {f}")
        print()
        print(f"  owned globs: {globs}")
        print(f"  shared allowlist: {SHARED_ALLOWLIST}")
        print(
            "\n  If you need a shared-code change, open a separate PR without "
            "the `# Group:` marker and request @course-maintainers review."
        )
        return 1

    print(f"[boundary] OK: {len(files)} file(s) changed, all inside {group!r} owned paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
