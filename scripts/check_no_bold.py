"""Fail when a documentation file uses markdown bold.

The house style in AGENTS.md is plain text, headings, tables and backticks, with
no bold. This gate enforces that.

It exists as a script rather than a grep because the naive grep for ``**``
cannot tell markdown bold from a glob pattern: ``**/*.md`` and ``etc/**`` are
ordinary content in a specification that describes file layouts, and they are
not bold. Three plan-check runs failed on exactly that false positive.

The rules applied here:

- a fenced code block is skipped entirely, fence markers included;
- inline code spans are removed before the line is examined;
- bold is a PAIRED ``**`` on one line with at least one non-space, non-star
  character between the pair, which is what markdown actually renders.

A glob survives all three: ``**/*.md`` has no closing pair, and a fenced YAML
block is skipped before it is ever read.
"""

from __future__ import annotations

import pathlib
import re
import sys

TARGETS = ("README.md", "AGENTS.md", "docs")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
BOLD = re.compile(r"\*\*[^*\s][^*]*\*\*")


def offending_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    in_fence = False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if BOLD.search(INLINE_CODE.sub("", raw)):
            found.append((number, raw.strip()))
    return found


def main() -> int:
    failures = 0
    for target in TARGETS:
        root = pathlib.Path(target)
        if not root.exists():
            continue
        paths = sorted(root.rglob("*.md")) if root.is_dir() else [root]
        for path in paths:
            for number, text in offending_lines(path):
                print(f"{path}:{number}: bold found: {text}")
                failures += 1
    if failures:
        print(f"\n{failures} bold occurrence(s). House style is plain text; see AGENTS.md.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
