"""Markdown rendering for curriculum content.

Renders authored markdown to HTML on save and sanitizes the result so a
raw ``<script>`` in a synced body is removed rather than executed.

``render_annotated_markdown`` is the unit-body entry point: it adds structured
code annotations (``community_base.curriculum.code_annotations``) on top of the
one markdown path in this module. There is no second renderer and no second
sanitizer -- the annotated block is markup this package generates from a parsed
structure after sanitization, through a template a site may override.
"""

import re

import markdown as markdown_lib
import nh3
from django.template.loader import render_to_string

from community_base.curriculum.code_annotations import build_render_plan

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


ANNOTATED_CODE_BLOCK_TEMPLATE = "curriculum/annotated_code_block.html"
ANNOTATED_CODE_BLOCK_HEADING = "Code annotations"


def render_annotated_markdown(text: str) -> str:
    """Render a unit body, expanding annotated code blocks into their markup.

    Bodies with no annotations render exactly like ``render_markdown``. An
    invalid annotation payload raises ``CodeAnnotationError`` so a malformed
    body fails rather than being published with its metadata showing.
    """

    if not text:
        return ""
    plan = build_render_plan(text)
    rendered = render_markdown(plan.markdown)
    for position, (token, block) in enumerate(plan.blocks, start=1):
        markup = render_to_string(
            ANNOTATED_CODE_BLOCK_TEMPLATE,
            {
                "block": block,
                "heading": ANNOTATED_CODE_BLOCK_HEADING,
                "heading_id": f"code-annotations-{position}",
            },
        ).strip()
        paragraph = f"<p>{token}</p>"
        if paragraph in rendered:
            rendered = rendered.replace(paragraph, markup, 1)
        else:
            rendered = rendered.replace(token, markup, 1)
    return rendered


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
