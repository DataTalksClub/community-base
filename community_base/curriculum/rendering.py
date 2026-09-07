"""Markdown rendering for curriculum content.

Renders authored markdown to HTML on save and sanitizes the result so a
raw ``<script>`` in a synced body is removed rather than executed.
"""

import re

import markdown as markdown_lib
import nh3

_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]

_SANITIZE_TAGS = frozenset(
    {
        "a",
        "abbr",
        "b",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_SANITIZE_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "div": {"class"},
    "span": {"class"},
    "code": {"class"},
    "pre": {"class"},
    "td": {"align"},
    "th": {"align"},
}

# ATX H1: a single ``#`` followed by a space, capturing the heading text.
_LEADING_H1_RE = re.compile(r"^(?P<hash>#)[ \t]+(?P<text>.+?)[ \t]*#*[ \t]*$")
_TRAILING_PUNCT_RE = re.compile(r"[.,:;!?]+$")
_WHITESPACE_RE = re.compile(r"\s+")


def render_markdown(text: str) -> str:
    """Render markdown to sanitized HTML."""

    if not text:
        return ""
    rendered = markdown_lib.markdown(text, extensions=_EXTENSIONS)
    return nh3.clean(rendered, tags=_SANITIZE_TAGS, attributes=_SANITIZE_ATTRIBUTES, link_rel=None)


def _normalise(text: str | None) -> str:
    if text is None:
        return ""
    text = text.strip()
    text = _WHITESPACE_RE.sub(" ", text)
    text = _TRAILING_PUNCT_RE.sub("", text).strip()
    return text.lower()


def strip_leading_title_h1(body: str, title: str) -> str:
    """Return ``body`` with its leading H1 removed if it matches ``title``.

    The page templates render the authored title as the page heading, so a
    body that opens with the same H1 would show the title twice. The H1 is
    only stripped when the first non-blank line is an ATX H1 whose text
    matches the title case-insensitively, whitespace-collapsed and ignoring
    trailing punctuation. Every other body is returned unchanged.
    """

    if not body or not title:
        return body

    target = _normalise(title)
    if not target:
        return body

    lines = body.splitlines(keepends=True)

    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1

    if idx == len(lines):
        return body

    match = _LEADING_H1_RE.match(lines[idx].rstrip("\r\n"))
    if not match:
        return body

    if _normalise(match.group("text")) != target:
        return body

    drop_to = idx + 1
    if drop_to < len(lines) and lines[drop_to].strip() == "":
        drop_to += 1

    return "".join(lines[drop_to:])
