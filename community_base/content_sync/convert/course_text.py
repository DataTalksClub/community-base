"""Course-conversion prose, path and asset helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from community_base.content_sync.kinds.base import ORDER_PREFIX_PATTERN

ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf")
STRIKETHROUGH = re.compile(r"~~([^~\s][^~]*)~~")
STYLE_ATTRIBUTE = re.compile(r'\s+style\s*=\s*(["\'])[^"\']*\1', re.IGNORECASE)
FENCE = re.compile(r"^(\s*)(```+|~~~+)")

# --- helpers ------------------------------------------------------------------


LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?\s*(?:\"[^\"]*\")?\)")


def _relative_links(body: str) -> list[tuple[int, str]]:
    """Every markdown link or image destination that is not external."""

    found: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(body.split("\n"), start=1):
        match = FENCE.match(line)
        if fence is not None:
            if match is not None and match.group(2).startswith(fence):
                fence = None
            continue
        if match is not None:
            fence = match.group(2)
            continue
        for destination in LINK.findall(line):
            if destination.startswith(("http://", "https://", "#", "mailto:", "//", "/")):
                continue
            if ":" in destination.split("/")[0]:
                continue
            found.append((number, destination))
    return found


def _join(source: str, target: str) -> str | None:
    parts = source.split("/")[:-1]
    for part in target.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _slug_of(name: str) -> str:
    return ORDER_PREFIX_PATTERN.sub("", name)


def _is_asset_dir(directory: Path) -> bool:
    files = []
    for item in directory.glob("**/*"):
        if item.is_file():
            files.append(item)
    return bool(files) and all(item.suffix.lower() in ASSET_SUFFIXES for item in files)


def _dropped(data: Mapping[str, Any], rel: str) -> list[str]:
    units = data.get("units")
    if not units:
        return []
    return [f"units -> the unit files of {rel}/ ({len(units)} of them)"]


def _convert_body(body: str, title: str) -> tuple[str, list[str]]:
    """The two body rewrites section 4.3 names, and the H1 section 3.3 forbids."""

    details: list[str] = []
    body, removed = _strip_leading_h1(body, title)
    if removed:
        details.append("removed the leading H1 that repeats the title")
    lines = body.split("\n")
    fence: str | None = None
    struck = styled = 0
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if fence is not None:
            if match is not None and match.group(2).startswith(fence):
                fence = None
            continue
        if match is not None:
            fence = match.group(2)
            continue
        rewritten, count = STRIKETHROUGH.subn(r"<del>\1</del>", line)
        struck += count
        rewritten, count = STYLE_ATTRIBUTE.subn("", rewritten)
        styled += count
        lines[index] = rewritten
    if struck:
        details.append(f"~~strikethrough~~ -> <del> ({struck})")
    if styled:
        details.append(f"removed a style attribute the sanitiser drops ({styled})")
    return "\n".join(lines), details


def _strip_leading_h1(body: str, title: str) -> tuple[str, bool]:
    stripped = body.lstrip("\n")
    first, _, rest = stripped.partition("\n")
    if not first.startswith("# "):
        return body, False
    if first[2:].strip().lower() != title.strip().lower():
        return body, False
    return rest.lstrip("\n"), True
