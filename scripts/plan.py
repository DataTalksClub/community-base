#!/usr/bin/env python3
"""Plan tooling: keeps docs/plan/STATUS.md in sync with the phase files.

Usage:
    python scripts/plan.py check     # every issue in phase files has a STATUS row and vice versa
    python scripts/plan.py sync      # add missing rows to STATUS.md, keep existing status/link
    python scripts/plan.py summary   # progress per phase and per repository
    python scripts/plan.py next      # issues whose dependencies are done and status is "todo"

No dependencies beyond the standard library.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "plan"
STATUS = PLAN / "STATUS.md"

REPO_BY_LETTER = {
    "C": "community-base",
    "A": "AI-Shipping-Labs/website",
    "D": "DataTalksClub/website",
    "R": "DataTalksClub/relay",
}
STATUSES = ("todo", "in-progress", "blocked", "review", "done", "skipped")

ISSUE_RE = re.compile(r"^## ([CADR]\d\.\d+) (.+)$")
DEPENDS_RE = re.compile(r"Depends on: ([^.\n]*(?:\.\d+[^.\n]*)*)")
ID_RE = re.compile(r"\b[CADR]\d\.\d+\b")
FREEZE_RE = re.compile(r"Freeze required: (yes|no)", re.IGNORECASE)


def load_issues() -> list[dict]:
    issues = []
    for phase_file in sorted(PLAN.glob("phase-*.md")):
        phase = phase_file.stem.split("-")[1]
        text = phase_file.read_text().splitlines()
        current = None
        for line in text:
            m = ISSUE_RE.match(line)
            if m:
                current = {
                    "id": m.group(1),
                    "title": m.group(2).strip(),
                    "phase": phase,
                    "repo": REPO_BY_LETTER[m.group(1)[0]],
                    "depends": [],
                    "freeze": "no",
                    "file": phase_file.name,
                }
                issues.append(current)
                continue
            if current is None:
                continue
            dm = DEPENDS_RE.search(line)
            if dm and not current["depends"]:
                current["depends"] = [i for i in ID_RE.findall(dm.group(1)) if i != current["id"]]
            fm = FREEZE_RE.search(line)
            if fm:
                current["freeze"] = fm.group(1).lower()
            if "Freeze weekend" in current["title"] or line.startswith("Playbook P13") or "P13" in line:
                current["freeze"] = "yes"
    return issues


def load_status() -> dict[str, dict]:
    rows = {}
    if not STATUS.exists():
        return rows
    for line in STATUS.read_text().splitlines():
        if not line.startswith("| ") or line.startswith("| Issue") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or not ID_RE.fullmatch(cells[0].strip("`")):
            continue
        rows[cells[0].strip("`")] = {
            "status": cells[5],
            "link": cells[6],
        }
    return rows


def render(issues: list[dict], status: dict[str, dict]) -> str:
    out = [
        "# Plan status",
        "",
        "Single source of truth for progress across all four repositories. Generated rows come from",
        "`docs/plan/phase-*.md`; the `Status` and `Link` columns are edited by hand (or with",
        "`python scripts/plan.py`). Allowed statuses: " + ", ".join(f"`{s}`" for s in STATUSES) + ".",
        "",
        "Update the row for an issue in the same pull request that starts it (`in-progress`, with the",
        "pull request link) and in the pull request that closes it (`done`). When the issue lives in",
        "another repository, open a small pull request here that only changes this file.",
        "",
        "Run `python scripts/plan.py summary` for totals and `python scripts/plan.py next` for the",
        "issues that can start now.",
        "",
    ]
    by_phase: dict[str, list[dict]] = {}
    for issue in issues:
        by_phase.setdefault(issue["phase"], []).append(issue)
    for phase in sorted(by_phase):
        out.append(f"## Phase {phase}")
        out.append("")
        out.append("| Issue | Repository | Title | Depends on | Freeze | Status | Link |")
        out.append("|---|---|---|---|---|---|---|")
        for issue in by_phase[phase]:
            row = status.get(issue["id"], {"status": "todo", "link": ""})
            deps = ", ".join(issue["depends"]) if issue["depends"] else ""
            out.append(
                f"| `{issue['id']}` | {issue['repo']} | {issue['title']} | {deps} | "
                f"{issue['freeze']} | {row['status']} | {row['link']} |"
            )
        out.append("")
    return "\n".join(out)


def cmd_check() -> int:
    issues = load_issues()
    status = load_status()
    ids = {i["id"] for i in issues}
    missing = sorted(ids - set(status))
    extra = sorted(set(status) - ids)
    bad = sorted(k for k, v in status.items() if v["status"] not in STATUSES)
    dangling = sorted({d for i in issues for d in i["depends"] if d not in ids})
    problems = 0
    for label, items in (
        ("issues without a STATUS row", missing),
        ("STATUS rows without an issue", extra),
        ("rows with an unknown status", bad),
        ("dependencies that do not exist", dangling),
    ):
        if items:
            problems += 1
            print(f"{label}: {', '.join(items)}")
    if not problems:
        print(f"OK: {len(issues)} issues, STATUS.md consistent")
    return 1 if problems else 0


def cmd_sync() -> int:
    issues = load_issues()
    status = load_status()
    STATUS.write_text(render(issues, status) + "\n")
    print(f"wrote {STATUS.relative_to(ROOT)} with {len(issues)} rows")
    return 0


def cmd_summary() -> int:
    issues = load_issues()
    status = load_status()
    print("phase  total  done  in-progress  blocked  todo")
    by_phase: dict[str, list[str]] = {}
    for i in issues:
        by_phase.setdefault(i["phase"], []).append(status.get(i["id"], {"status": "todo"})["status"])
    for phase in sorted(by_phase):
        s = by_phase[phase]
        print(
            f"{phase:>5}  {len(s):>5}  {s.count('done'):>4}  {s.count('in-progress'):>11}  "
            f"{s.count('blocked'):>7}  {s.count('todo'):>4}"
        )
    print()
    print("repository                 total  done")
    by_repo: dict[str, list[str]] = {}
    for i in issues:
        by_repo.setdefault(i["repo"], []).append(status.get(i["id"], {"status": "todo"})["status"])
    for repo, s in by_repo.items():
        print(f"{repo:<26} {len(s):>5}  {s.count('done'):>4}")
    return 0


def cmd_next() -> int:
    issues = load_issues()
    status = load_status()
    done = {k for k, v in status.items() if v["status"] in ("done", "skipped")}
    ready = [
        i for i in issues
        if status.get(i["id"], {"status": "todo"})["status"] == "todo"
        and all(d in done for d in i["depends"])
    ]
    if not ready:
        print("nothing ready: every todo issue has an unfinished dependency")
        return 0
    lowest_phase = min(i["phase"] for i in ready)
    for i in ready:
        marker = "  " if i["phase"] == lowest_phase else "  (later phase)"
        print(f"{i['id']:<6} {i['repo']:<26} {i['title']}{marker}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"check": cmd_check, "sync": cmd_sync, "summary": cmd_summary, "next": cmd_next}
    if len(argv) != 2 or argv[1] not in commands:
        print(__doc__)
        return 2
    return commands[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
