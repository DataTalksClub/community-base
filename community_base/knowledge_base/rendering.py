"""Rendering and sanitizing for knowledge base pages.

``render_markdown`` renders a page body to HTML and sanitizes the result;
``sanitize_rendered_html`` sanitizes HTML a site parser produced itself (a
parser may render blocks its own way, but the stored body must always pass
one code-owned sanitizer).

The allowlist is lifted from DataTalksClub's
``content/services.py:sanitize_rendered_html`` (tags, attribute rules and URL
protocols) so both sites' knowledge base content is held to the same policy
instead of a second, divergent one. One deliberate extension: an ``img src``
may also be an absolute ``http(s)`` URL, because the sites serve images from
their own CDN hosts while DTC's release pipeline only ever produced
site-absolute paths. Everything else is byte-for-byte the donor policy,
re-expressed for ``nh3`` (this package's sanitizer, also used by
``curriculum``) instead of Bleach.
"""

import re
from urllib.parse import urlsplit

import markdown as markdown_lib
import nh3

_EXTENSIONS = ["fenced_code", "tables", "sane_lists"]

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
# the heading ids a site injects for its table of contents are dropped before
# the filter ever sees them.
_SANITIZE_ATTRIBUTES = {
    "*": {"class", "id", "lang", "title"},
    "a": {"href", "rel"},
    "img": {"alt", "height", "loading", "src", "width"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "time": {"datetime"},
}


def _allowed_attribute(tag: str, attribute: str, value: str) -> str | None:
    """nh3 attribute filter lifting DTC's ``_allowed_render_attribute``."""

    if attribute in {"class", "id", "lang", "title"}:
        return value
    if tag == "a" and attribute in {"href", "rel"}:
        return value
    if tag == "img" and attribute == "src":
        return value if is_admitted_site_image_src(value) else None
    if tag == "img" and attribute in {"alt", "height", "loading", "width"}:
        return value
    if tag in {"td", "th"} and attribute in {"colspan", "rowspan"}:
        return value
    if tag == "th" and attribute == "scope":
        return value
    if tag == "time" and attribute == "datetime":
        return value
    return None


def sanitize_rendered_html(rendered_html: str) -> str:
    """Sanitize already-rendered HTML with the shared knowledge base allowlist."""

    return nh3.clean(
        rendered_html,
        tags=_SANITIZE_TAGS,
        attributes=_SANITIZE_ATTRIBUTES,
        attribute_filter=_allowed_attribute,
        url_schemes=_URL_SCHEMES,
        link_rel=None,
        strip_comments=True,
    )


def render_markdown(text: str) -> str:
    """Render markdown to sanitized HTML."""

    if not text:
        return ""
    return sanitize_rendered_html(markdown_lib.markdown(text, extensions=_EXTENSIONS))
