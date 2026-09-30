"""The one markdown dialect and the one sanitizer for synced content.

`FORMAT.md` section 4 is the specification this module implements. Everything a
synced repository publishes as HTML passes through :func:`render_document`, and
everything stored as HTML passes through :func:`sanitize_rendered_html`, whether
this module rendered it or a site parser did. A second renderer or a second
allowlist is a defect, not an extension point: a site adds a python-markdown
extension through ``COMMUNITY_BASE["MARKDOWN_EXTENSIONS"]`` and its output is
still sanitized here.

The dialect is python-markdown with ``fenced_code``, ``tables`` and
``sane_lists``. ``attr_list`` and ``md_in_html`` are deliberately absent, so a
kramdown attribute list is inert text the validator rejects rather than markup.
Two package extensions add the ``mermaid`` and ``embed`` fences of section 4.1.

The allowlist and the ``img src`` rule are lifted from DataTalksClub's
``content/services.py:sanitize_rendered_html``, re-expressed for ``nh3``. One
deliberate extension to the donor policy: an ``img src`` may also be an absolute
``http(s)`` URL, because the sites serve images from their own CDN hosts while
DTC's release pipeline only ever produced site-absolute paths.

The heading-id algorithm is DataTalksClub's
``content/docs_projection.py:_heading_ids``, kept because the point of keeping it
is that DTC's pinned fragment contracts keep resolving. It counts repeats from
zero: a second ``Setup`` is ``setup-1`` and a third is ``setup-2``. The design
document `docs/plan/evidence/unified-content-format-2026-09-17.md` named both
that scheme and a ``-2``, ``-3`` one; the donor decides, and `FORMAT.md` records
the decision.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser

import markdown as markdown_lib
import yaml
from markdown.preprocessors import Preprocessor

from .html_policy import is_admitted_site_image_src as is_admitted_site_image_src
from .html_policy import sanitize_rendered_html as sanitize_rendered_html

# --- the dialect, section 4.1 ------------------------------------------------

#: The package extension set. A site appends to it and never replaces it.
PACKAGE_MARKDOWN_EXTENSIONS = ("fenced_code", "tables", "sane_lists")

#: One embeddable video provider to the public URL of one of its videos.
EMBED_URLS = {
    "youtube": "https://www.youtube.com/watch?v={id}",
    "loom": "https://www.loom.com/share/{id}",
}

CB_EMBED_CLASS = "cb-embed"
MERMAID_CLASS = "mermaid"

_FENCE_OPEN = re.compile(r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})[ ]*(?P<info>\S*)[ ]*$")
_FENCE_CLOSE = re.compile(r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})[ ]*$")
_EMBED_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _mermaid_html(source: str) -> str:
    """A `mermaid` fence: escaped source the site's JavaScript draws."""

    return f'<pre class="{MERMAID_CLASS}">{html.escape(source, quote=False)}</pre>'


def _embed_html(source: str) -> str | None:
    """An `embed` fence, or None when the body is not a valid `{type, id}` map.

    An invalid body is left as an ordinary fenced block: `check_content` already
    reports it against rule 4.1, and rendering is not the place to lose content.
    No iframe is ever stored; the site hydrates the hooks.
    """

    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError:
        return None
    if not isinstance(data, Mapping) or set(data) - {"type", "id"}:
        return None
    embed_type = data.get("type")
    identifier = data.get("id")
    if isinstance(identifier, int) and not isinstance(identifier, bool):
        identifier = str(identifier)
    if embed_type not in EMBED_URLS or not isinstance(identifier, str):
        return None
    if _EMBED_ID.fullmatch(identifier) is None:
        return None
    url = EMBED_URLS[embed_type].format(id=identifier)
    return (
        f'<div class="{CB_EMBED_CLASS}" data-embed-type="{embed_type}"'
        f' data-embed-id="{identifier}"><a href="{url}">{url}</a></div>'
    )


class _PackageFences(Preprocessor):
    """Turn `mermaid` and `embed` fences into stashed HTML before `fenced_code`.

    Scanning is fence-aware: an ordinary fence is copied through to its closing
    line untouched, so a documentation page that shows a `mermaid` fence inside a
    longer fence keeps showing it instead of drawing it.
    """

    def run(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        index = 0
        while index < len(lines):
            opening = _FENCE_OPEN.match(lines[index])
            if opening is None:
                out.append(lines[index])
                index += 1
                continue
            close = self._closing_line(lines, index, opening.group("fence"))
            end = len(lines) if close is None else close
            body = "\n".join(lines[index + 1 : end])
            rendered = self._fence_html(opening.group("info"), body)
            if rendered is None:
                out.extend(lines[index : end + 1])
            else:
                out.append(self.md.htmlStash.store(rendered))
            index = end + 1
        return out

    @staticmethod
    def _fence_html(info: str, body: str) -> str | None:
        if info == MERMAID_CLASS:
            return _mermaid_html(body)
        if info == "embed":
            return _embed_html(body)
        return None

    @staticmethod
    def _closing_line(lines: list[str], start: int, fence: str) -> int | None:
        for number in range(start + 1, len(lines)):
            closing = _FENCE_CLOSE.match(lines[number])
            if closing is None:
                continue
            candidate = closing.group("fence")
            if candidate[0] == fence[0] and len(candidate) >= len(fence):
                return number
        return None


class PackageFenceExtension(markdown_lib.extensions.Extension):
    """Register the package fences ahead of `fenced_code` (priority 25)."""

    def extendMarkdown(self, md) -> None:  # noqa: N802 - python-markdown's API
        md.preprocessors.register(_PackageFences(md), "community_base_fences", 27)


def markdown_extensions() -> list:
    """The package extension list with the site's appended, never replaced."""

    from community_base.kernel.conf import get

    configured = get("MARKDOWN_EXTENSIONS") or []
    return [*PACKAGE_MARKDOWN_EXTENSIONS, PackageFenceExtension(), *configured]


# --- heading ids, section 4.1 ------------------------------------------------

_HEADING = re.compile(
    r"(?P<open><h(?P<level>[1-6])>)(?P<body>.*?)(?P<close></h(?P=level)>)",
    re.DOTALL,
)


class _HeadingText(HTMLParser):
    """Collect visible text from one rendered heading without trusting its HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def heading_text(value: str) -> str:
    """The visible text of one rendered heading, whitespace collapsed."""

    parser = _HeadingText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


def heading_slug(value: str) -> str:
    """The donor slug: NFKD, ASCII, lowercase, non-alphanumerics to `-`."""

    normalized = unicodedata.normalize("NFKD", html.unescape(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "section"


class HeadingIdAssigner:
    """Hand out one heading id per heading, in document order.

    The counting is the donor's and the reason it is kept is written in the
    module docstring: the first `Setup` is `setup`, the second `setup-1`, the
    third `setup-2`. `check_content` and the renderer share this object so the
    fragment a validator accepts is the fragment a rendered page carries.
    """

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def assign(self, text: str) -> str:
        base = heading_slug(text)
        count = self._seen.get(base, 0)
        self._seen[base] = count + 1
        return base if count == 0 else f"{base}-{count}"


def inject_heading_ids(rendered_html: str) -> tuple[str, tuple[dict[str, object], ...]]:
    """Add an `id` to every rendered heading; return the HTML and the headings.

    Only an attribute-less `<hN>` is rewritten, as in the donor: python-markdown
    emits no heading attributes under this extension set, and a heading an author
    wrote as raw HTML keeps the id that author gave it.
    """

    assigner = HeadingIdAssigner()
    headings: list[dict[str, object]] = []

    def replace(match: re.Match[str]) -> str:
        text = heading_text(match.group("body"))
        slug = assigner.assign(text)
        level = int(match.group("level"))
        headings.append({"level": level, "id": slug, "title": text})
        return f'<h{level} id="{slug}">{match.group("body")}</h{level}>'

    return _HEADING.sub(replace, rendered_html), tuple(headings)


# --- plain text, section 4.1 -------------------------------------------------


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(rendered_html: str) -> str:
    """The search text of a rendered document: visible text, whitespace collapsed.

    The parts are joined without a separator, unlike :func:`heading_text`, which
    keeps the donor's join because heading ids depend on it. Markdown puts a
    newline between block elements, so words do not run together, and an inline
    element no longer splits the word it marks up.
    """

    if not rendered_html:
        return ""
    parser = _VisibleText()
    parser.feed(rendered_html)
    return " ".join("".join(parser.parts).split())


# --- the leading H1, section 4.1 ---------------------------------------------

# ATX H1: a single ``#`` followed by a space, capturing the heading text.
_LEADING_H1_RE = re.compile(r"^(?P<hash>#)[ \t]+(?P<text>.+?)[ \t]*#*[ \t]*$")
_TRAILING_PUNCT_RE = re.compile(r"[.,:;!?]+$")
_WHITESPACE_RE = re.compile(r"\s+")


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


# --- the one rendering entry point -------------------------------------------


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    """One rendered body: the stored HTML, its headings and its search text."""

    html: str
    headings: tuple[dict[str, object], ...] = ()
    text: str = ""


def render_html(body: str, title: str = "") -> tuple[str, tuple[dict[str, object], ...]]:
    """The dialect and the heading ids, before the sanitizer runs.

    This is the seam `FORMAT.md` sections 3.6 and 3.7 rewrite in: an asset path
    and a cross-reference are resolved against the repository once the markdown
    is HTML, and the rewritten HTML is then sanitized by the caller. A relative
    `img src` does not survive the allowlist, so a rewrite that ran after the
    sanitizer would rewrite an attribute that is already gone.

    There is still one markdown pass and one sanitizer: :func:`render_document`
    is this function plus :func:`sanitize_rendered_html`, and a caller that
    needs the seam composes the same two calls rather than rendering again.
    """

    if not body:
        return "", ()
    source = strip_leading_title_h1(body, title) if title else body
    rendered = markdown_lib.markdown(source, extensions=markdown_extensions())
    return inject_heading_ids(rendered)


def render_document(body: str, title: str = "") -> RenderedDocument:
    """Render one document body: dialect, heading ids, sanitizer, search text.

    The order is the donor's and `FORMAT.md` section 4.2 keeps it: render, then
    inject heading ids, then sanitize. Sanitizing is always last, so nothing an
    extension emits reaches storage unchecked.
    """

    if not body:
        return RenderedDocument("")
    rendered, headings = render_html(body, title)
    rendered = sanitize_rendered_html(rendered)
    return RenderedDocument(rendered, headings, plain_text(rendered))


def render_markdown(text: str) -> str:
    """Render markdown to sanitized HTML: `render_document` without its metadata."""

    return render_document(text).html
