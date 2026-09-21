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
from urllib.parse import urlsplit

import markdown as markdown_lib
import nh3
import yaml
from markdown.preprocessors import Preprocessor

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


# --- the sanitizer, section 4.2 ----------------------------------------------

# Lifted from DTC ``_CONTENT_ALLOWED_TAGS``.
_SANITIZE_TAGS = frozenset(
    {
        "a",
        "abbr",
        "b",
        "blockquote",
        "br",
        "code",
        "dd",
        "del",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "kbd",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "time",
        "tr",
        "ul",
    }
)

# Lifted from DTC ``_CONTENT_ALLOWED_PROTOCOLS``.
_URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})

_PCHAR_PATH = re.compile(r"^(?:/|[A-Za-z0-9._~!$&'()*+,;=:@%-])+$")
_PERCENT_HEXITS = frozenset("0123456789abcdefABCDEF")
_PERCENT_DECODE_DENIED = frozenset({"/", "\\", "?", "#", "%"})


def _canonical_image_path_segment(segment: str) -> bool:
    """Admit one raw path segment only if browser parsing cannot move it.

    Lifted from DTC ``_canonical_image_path_segment``: rejects percent-decoded
    dot segments (WHATWG collapses ``.``/``..``), encoded separators, malformed
    or second-order percent escapes, and any decoded byte outside plain ASCII
    path characters.
    """

    if not segment:
        return True
    decoded: list[str] = []
    index = 0
    while index < len(segment):
        character = segment[index]
        if character == "%":
            hexits = segment[index + 1 : index + 3]
            if len(hexits) != 2 or any(hexit not in _PERCENT_HEXITS for hexit in hexits):
                return False
            decoded_character = chr(int(hexits, 16))
            if (
                not decoded_character.isascii()
                or decoded_character in _PERCENT_DECODE_DENIED
                or decoded_character.isspace()
                or ord(decoded_character) < 0x20
                or ord(decoded_character) == 0x7F
            ):
                return False
            decoded.append(decoded_character)
            index += 3
        else:
            decoded.append(character)
            index += 1
    return "".join(decoded) not in {".", ".."}


def is_admitted_site_image_src(value: str) -> bool:
    """Decide whether an ``img src`` may ship in sanitized rendered content.

    The site-absolute branch is lifted from DTC's
    ``is_admitted_site_image_src``: canonical ASCII paths, no repeated
    separators, no query or fragment, well-formed single-escape percent
    encoding whose decoded form is itself a plain path segment - admission is
    deliberately stricter than WHATWG resolution but never admits a
    destination a browser would resolve onto a different application route.
    The absolute-URL branch admits ``http(s)`` URLs with a host and no
    credentials, so a site whose images live on its own CDN renders them.
    """

    if value.startswith(("http://", "https://")):
        parts = urlsplit(value)
        return bool(parts.scheme in ("http", "https") and parts.netloc) and "@" not in parts.netloc
    return (
        value.startswith("/")
        and not value.startswith("//")
        and "//" not in value
        and "\\" not in value
        and "?" not in value
        and "#" not in value
        and value.isascii()
        and not any(
            character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
            for character in value
        )
        and _PCHAR_PATH.fullmatch(value) is not None
        and all(_canonical_image_path_segment(segment) for segment in value.split("/")[1:])
    )


# nh3 consults ``attribute_filter`` only for attributes its own allowlist
# already admits, so the filter below cannot widen anything on its own. This
# map opens exactly the attributes ``_allowed_attribute`` decides on -- it is
# the gate; the map only lets the question be asked. Without the ``*`` entry
# the heading ids this module injects are dropped before the filter sees them.
_SANITIZE_ATTRIBUTES = {
    "*": {"class", "id", "lang", "title"},
    "a": {"href", "rel", "target"},
    "div": {"data-embed-id", "data-embed-type", "data-event-widget"},
    "img": {"alt", "data-theme-figure", "height", "loading", "src", "width"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "time": {"datetime"},
}

_EMBED_ATTRIBUTES = frozenset({"data-embed-id", "data-embed-type"})
_EVENT_WIDGET_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _allowed_attribute(tag: str, attribute: str, value: str) -> str | None:
    """nh3 attribute filter lifting DTC's ``_allowed_render_attribute``."""

    if attribute in {"class", "id", "lang", "title"}:
        return value
    if tag == "a" and attribute in {"href", "rel"}:
        return value
    if tag == "a" and attribute == "target":
        return value if value == "_blank" else None
    if tag == "div" and attribute in _EMBED_ATTRIBUTES:
        return value
    if tag == "div" and attribute == "data-event-widget":
        return value if _EVENT_WIDGET_SLUG.fullmatch(value) else None
    if tag == "img" and attribute == "src":
        return value if is_admitted_site_image_src(value) else None
    if tag == "img" and attribute in {"alt", "data-theme-figure", "height", "loading", "width"}:
        return value
    if tag in {"td", "th"} and attribute in {"colspan", "rowspan"}:
        return value
    if tag == "th" and attribute == "scope":
        return value
    if tag == "time" and attribute == "datetime":
        return value
    return None


def sanitize_rendered_html(rendered_html: str) -> str:
    """Sanitize already-rendered HTML with the one package allowlist."""

    return nh3.clean(
        rendered_html,
        tags=_SANITIZE_TAGS,
        attributes=_SANITIZE_ATTRIBUTES,
        attribute_filter=_allowed_attribute,
        url_schemes=_URL_SCHEMES,
        link_rel=None,
        strip_comments=True,
    )


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
