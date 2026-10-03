"""Body conversion: one ordered transform pipeline and fence state."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from community_base.content_sync.convert.article_profile import unwrap_raw_fences
from community_base.content_sync.convert.contracts import Refused

KRAMDOWN_LINE = re.compile(r"^\s*\{:\s*[.#][^}]*\}\s*$")

KRAMDOWN_INLINE = re.compile(r"\s*\{:\s*[.#][^}]*\}")

RELATIVE_URL = re.compile(r"\{\{\s*'(?P<path>[^']+)'\s*\|\s*relative_url\s*\}\}")

SITE_BASEURL = re.compile(r"\{\{\s*site\.baseurl\s*\}\}(?P<path>\S*)")

LIQUID = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")

WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

STYLE_ATTRIBUTE = re.compile(r'\s+style\s*=\s*(["\'])[^"\']*\1', re.IGNORECASE)

STRIKETHROUGH = re.compile(r"~~([^~\s][^~]*)~~")

FENCE = re.compile(r"^(\s*)(```+|~~~+)")

INLINE_CODE = re.compile(r"`[^`]*`")

ABSOLUTE_LINK = re.compile(r"(?P<open>!?\[[^\]]*\]\()(?P<path>/[^)\s]*)\)")

ABSOLUTE_SRC = re.compile(r"(?P<open>\bsrc\s*=\s*[\"'])(?P<path>/[^\"']*)")


class BodyConversion:
    def __init__(self, urls: dict[str, str], profile_name: str = "") -> None:
        self.urls = urls
        self.profile_name = profile_name

    def convert(self, collection, page, titles, slugs) -> tuple[str, list[str]]:
        body = str(page["body"])
        details = []
        if self.profile_name == "dtc-articles":
            body, wrappers = unwrap_raw_fences(body)
            if wrappers:
                details.append(f"removed raw wrappers around fenced code: {wrappers}")
        if self.profile_name == "dtc-articles":
            body, embeds = _article_youtube_embeds(body)
        else:
            body, embeds = _youtube_embeds(body)
        _check_fences(body)
        if embeds:
            details.append(f"youtube.html include -> embed fence: {embeds}")
        body, removed = _strip_leading_h1(body, str(page["front"].get("title") or ""))
        if removed:
            details.append("removed the leading H1 that repeats the title")
        counts = dict.fromkeys(("kramdown", "relative_url", "wikilink", "style", "del"), 0)
        converted = self._lines(body, collection, page, titles, slugs, counts)
        for name, count in counts.items():
            if count:
                details.append(f"{name}: {count}")
        return converted, details

    def _lines(self, body, collection, page, titles, slugs, counts) -> str:
        out = []
        fence = None
        for line in body.split("\n"):
            match = FENCE.match(line)
            if fence is not None:
                out.append(line)
                if match is not None and match.group(2).startswith(fence):
                    fence = None
                continue
            if match is not None:
                fence = match.group(2)
                out.append(line)
                continue
            if KRAMDOWN_LINE.match(line):
                counts["kramdown"] += 1
                continue
            out.append(self._line(line, collection, page, titles, slugs, counts))
        return "\n".join(out)

    def _line(self, line, collection, page, titles, slugs, counts) -> str:
        line, count = KRAMDOWN_INLINE.subn("", line)
        counts["kramdown"] += count
        line, count = RELATIVE_URL.subn(lambda found: self._url(found, page), line)
        counts["relative_url"] += count
        line, count = SITE_BASEURL.subn(lambda found: self._url(found, page), line)
        counts["relative_url"] += count
        line, count = STYLE_ATTRIBUTE.subn("", line)
        counts["style"] += count
        line, count = STRIKETHROUGH.subn(r"<del>\1</del>", line)
        counts["del"] += count
        line, count = self._absolute(collection, line, page)
        counts["relative_url"] += count
        line = _wikilinks(line, collection, titles, slugs, counts)
        if LIQUID.search(INLINE_CODE.sub("", line)):
            raise Refused("4.1", f"Liquid this conversion does not read: {line.strip()[:80]}")
        return line

    def _absolute(self, collection, line, page) -> tuple[str, int]:
        target = str(page["target"])
        count = 0

        def replace(found):
            nonlocal count
            destination, _, fragment = found.group("path").partition("#")
            resolved = self._destination(collection, destination)
            if resolved is None:
                return found.group(0)
            count += 1
            closing = ""
            if found.group(0).endswith(")"):
                closing = ")"
            written = _relative_to(resolved, target)
            if fragment:
                written = f"{written}#{fragment}"
            return f"{found.group('open')}{written}{closing}"

        line = ABSOLUTE_LINK.sub(replace, line)
        return ABSOLUTE_SRC.sub(replace, line), count

    def _destination(self, collection, destination) -> str | None:
        resolved = self.urls.get(destination.rstrip("/") + "/")
        if resolved is None and destination.split("/")[1:2]:
            root = destination.split("/")[1]
            if root in collection.absolute_roots:
                resolved = destination.lstrip("/")
        return resolved

    def _url(self, found: re.Match[str], page: Mapping[str, Any]) -> str:
        path = found.group("path")
        target = self.urls.get(path.rstrip("/") + "/")
        if target is None:
            return path
        return _relative_to(target, str(page["target"]))


def _wikilinks(line, collection, titles, slugs, counts) -> str:
    for token in WIKILINK.findall(line):
        slug = titles.get(token.strip().lower())
        if not slug:
            slug = None
            if token.strip() in slugs:
                slug = token.strip()
        if slug is None:
            raise Refused(
                "3.7", f"[[{token}]] names no page of this collection and is not rewritten"
            )
        line = line.replace(f"[[{token}]]", f"[{token}]({collection.kind}:{slug})")
        counts["wikilink"] += 1
    return line


YOUTUBE_INCLUDE = re.compile(
    r'^\s*\{%\s*include\s+youtube\.html\s+video_id="(?P<id>[^"]+)"\s*%\}\s*$', re.MULTILINE
)


def _youtube_embeds(body: str) -> tuple[str, int]:
    """`FORMAT.md` section 4.3: the one include the format has a shape for."""

    def replace(found: re.Match[str]) -> str:
        return f"```embed\ntype: youtube\nid: {found.group('id')}\n```"

    return YOUTUBE_INCLUDE.subn(replace, body)


def _article_youtube_embeds(body: str) -> tuple[str, int]:
    """Convert supported includes outside fences without changing code bytes."""

    output = []
    count = 0
    fence = None
    for line in body.splitlines(keepends=True):
        match = FENCE.match(line)
        if fence is not None:
            output.append(line)
            if match is not None and match.group(2).startswith(fence):
                fence = None
            continue
        if match is not None:
            fence = match.group(2)
            output.append(line)
            continue
        found = YOUTUBE_INCLUDE.fullmatch(line.rstrip("\r\n"))
        if found is None:
            output.append(line)
            continue
        output.append(_article_youtube_fence(found.group("id"), line))
        count += 1
    return "".join(output), count


def _article_youtube_fence(video_id: str, source_line: str) -> str:
    line_end = ""
    separator = "\n"
    if source_line.endswith("\r\n"):
        line_end = separator = "\r\n"
    elif source_line.endswith("\n"):
        line_end = "\n"
    return separator.join(("```embed", "type: youtube", f"id: {video_id}", "```")) + line_end


def _check_fences(body: str) -> None:
    """Refuse a body whose last code fence is never closed.

    Everything after an unterminated fence is code to the renderer and to this
    conversion alike, so a link inside it is not rewritten and a construct
    inside it is not seen. Converting such a file would silently leave half of
    it as it was; the author closes the fence first.
    """

    fence: str | None = None
    for line in body.split("\n"):
        match = FENCE.match(line)
        if fence is None:
            if match is not None:
                fence = match.group(2)
        elif match is not None and match.group(2).startswith(fence):
            fence = None
    if fence is not None:
        raise Refused("4.1", f"a {fence} code fence is opened and never closed")


def _relative_to(target: str, source: str) -> str:
    """`target` written relative to the directory `source` sits in."""

    base = Path(source).parent.parts
    parts = Path(target).parts
    shared = 0
    while shared < min(len(base), len(parts) - 1) and base[shared] == parts[shared]:
        shared += 1
    up = [".."] * (len(base) - shared)
    return "/".join([*up, *parts[shared:]]) or target


def _strip_leading_h1(body: str, title: str) -> tuple[str, bool]:
    stripped = body.lstrip("\n")
    first, _, rest = stripped.partition("\n")
    if not first.startswith("# ") or first[2:].strip().lower() != title.strip().lower():
        return body, False
    return rest.lstrip("\n"), True
