"""The shared HTML allowlist and source-admission policy (FORMAT section 4.2)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import nh3

# Lifted from DTC ``_CONTENT_ALLOWED_TAGS``.
_SANITIZE_TAGS = frozenset(
    {
        "a",
        "abbr",
        "aside",
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
        "section",
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


def _decoded_path_character(hexits: str) -> str | None:
    """Decode one escape only when it cannot change URL path boundaries."""

    if len(hexits) != 2 or any(hexit not in _PERCENT_HEXITS for hexit in hexits):
        return None
    character = chr(int(hexits, 16))
    if (
        not character.isascii()
        or character in _PERCENT_DECODE_DENIED
        or character.isspace()
        or ord(character) < 0x20
        or ord(character) == 0x7F
    ):
        return None
    return character


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
            decoded_character = _decoded_path_character(segment[index + 1 : index + 3])
            if decoded_character is None:
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
    return _is_canonical_site_image_path(value)


def _is_canonical_site_image_path(value: str) -> bool:
    """Apply the site-absolute branch independently from CDN URL admission."""

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
        if value == "_blank":
            return value
        return None
    if tag == "div" and attribute in _EMBED_ATTRIBUTES:
        return value
    if tag == "div" and attribute == "data-event-widget":
        if _EVENT_WIDGET_SLUG.fullmatch(value):
            return value
        return None
    if tag == "img" and attribute == "src":
        if is_admitted_site_image_src(value):
            return value
        return None
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
