"""Refuse a release whose tag name disagrees with the version in the tagged commit.

This exists because it already went wrong. The `v0.4.7` tag was cut at a commit
whose `pyproject.toml` still said `0.4.6`; a consumer locked that commit; the tag
was then moved to the follow-up commit carrying the bump. The two differ only in
the version string, so nothing behaved differently, but a consumer that re-locks
gets different bytes than one that locked earlier, which is exactly what pinning
a tag is supposed to prevent (decision D1).

Two rules follow, and this script enforces the first:

1. The tag name must equal the version recorded in the commit it points at, in
   both `pyproject.toml` and `community_base/__init__.py`. A release cut before
   its own version bump fails here instead of shipping.
2. A published tag is immutable. Never move one; cut the next version instead.
   That rule cannot be enforced from inside a job running at the tag, so it lives
   in playbook P15 and in the branch protection settings.

Usage: `python scripts/check_release_tag.py v0.4.8`, or with no argument it reads
`GITHUB_REF_NAME`.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

PYPROJECT_VERSION = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
DUNDER_VERSION = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)


def _read(path: str, pattern: re.Pattern[str]) -> str | None:
    text = pathlib.Path(path).read_text(encoding="utf-8")
    found = pattern.search(text)
    return found.group(1) if found else None


def main(argv: list[str]) -> int:
    tag = argv[1] if len(argv) > 1 else os.environ.get("GITHUB_REF_NAME", "")
    if not tag:
        print("No tag given and GITHUB_REF_NAME is unset.")
        return 2
    if not tag.startswith("v"):
        print(f"Tag {tag!r} does not start with 'v'.")
        return 2
    expected = tag[1:]

    pyproject = _read("pyproject.toml", PYPROJECT_VERSION)
    dunder = _read("community_base/__init__.py", DUNDER_VERSION)

    problems = []
    if pyproject is None:
        problems.append("pyproject.toml has no top-level version")
    elif pyproject != expected:
        problems.append(f"pyproject.toml says {pyproject}, tag says {expected}")
    if dunder is None:
        problems.append("community_base/__init__.py has no __version__")
    elif dunder != expected:
        problems.append(f"community_base/__init__.py says {dunder}, tag says {expected}")

    if problems:
        print(f"Release tag {tag} disagrees with the commit it points at:")
        for problem in problems:
            print(f"  {problem}")
        print()
        print("Cut the tag at a commit that carries its own version bump.")
        print("Do not move the published tag; that is what broke v0.4.7.")
        return 1

    print(f"Release tag {tag} matches the tagged commit: {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
