"""Structured code annotations authored alongside curriculum unit bodies.

An author marks up a fenced code block by placing a standalone HTML comment
immediately after the closing fence::

    ```python
    first = 1

    third = first + 2
    ```
    <!--
    structured: true
    code_annotations:
      - line: 1
        text: Set the initial value.
      - lines: "2-3"
        text: The blank line still counts.
    -->

This module owns the authoring contract and nothing else: it validates the
payload, strips it from the markdown, and returns a structured representation
of every annotated block. It emits no HTML and imports no Django, so the same
parse result drives sync-time validation, a default template shipped by this
package, and any markup a site prefers to render itself.

The contract is the one specified on AI-Shipping-Labs/website#1589, so a body
authored for one site parses identically on the other.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from yaml.tokens import AnchorToken, KeyToken, ScalarToken, TagToken

EN_DASH = "\N{EN DASH}"

# Fences whose language is claimed by a renderer extension rather than being
# code. They are never annotatable, on either site.
SPECIAL_FENCE_LANGUAGES = frozenset({"eventwidget", "mermaid"})

_FENCE_OPEN_RE = re.compile(r"^(?P<indent>[ \t]{0,3})(?P<marker>`{3,}|~{3,})(?P<info>[^\r\n]*)$")
_COMMENT_OPEN_RE = re.compile(r"^[ \t]*<!--[ \t]*$")
_COMMENT_CLOSE_RE = re.compile(r"^[ \t]*--\>[ \t]*$")
_RESERVED_KEY_RE = re.compile(
    r'(?:(?P<quote>["\'])(?:structured|code_annotations)(?P=quote)'
    r"|\b(?:structured|code_annotations))\s*:"
)
_LINES_RE = re.compile(r"^(?P<start>[1-9][0-9]*)-(?P<end>[1-9][0-9]*)$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_+.#-]+$")
_ATTR_LANGUAGE_RE = re.compile(r"\.([A-Za-z0-9_+-]+)(?=[\s}])")
_WHITESPACE_RE = re.compile(r"\s+")
_RESERVED_KEYS = frozenset({"structured", "code_annotations"})
_ANNOTATION_KEYS = frozenset({"line", "lines", "text"})


class CodeAnnotationError(ValueError):
    """A curriculum unit's code annotation payload is invalid."""


@dataclass(frozen=True, slots=True)
class CodeAnnotation:
    """One note attached to a line or an inclusive range of lines."""

    start: int
    end: int
    text: str

    @property
    def label(self) -> str:
        """The reader-facing range label, ready to print."""

        if self.start == self.end:
            return f"Line {self.start}"
        return f"Lines {self.start}{EN_DASH}{self.end}"


@dataclass(frozen=True, slots=True)
class CodeLine:
    """One source line of an annotated block, with its highlight state."""

    number: int
    text: str
    is_highlighted: bool


@dataclass(frozen=True, slots=True)
class AnnotatedCodeBlock:
    """A fenced code block together with the notes authored against it."""

    language: str
    lines: tuple[CodeLine, ...]
    annotations: tuple[CodeAnnotation, ...]


@dataclass(frozen=True, slots=True)
class ParsedUnitBody:
    """The result of parsing a unit body.

    ``markdown`` is the body with every annotation payload removed, so it can
    be handed to an ordinary markdown renderer. ``blocks`` holds one entry per
    fenced code block in document order; ``None`` marks a block with no
    annotations, and a special fence is always ``None``.
    """

    markdown: str
    blocks: tuple[AnnotatedCodeBlock | None, ...]


@dataclass(frozen=True, slots=True)
class RenderPlan:
    """A rendering seam: markdown with one opaque token per annotated block.

    ``markdown`` renders through the ordinary markdown pipeline; each token in
    ``blocks`` then appears in the rendered HTML as its own paragraph and is
    swapped for whatever markup the caller produces for that block. This keeps
    block identity exact instead of matching rendered elements by position.
    """

    markdown: str
    blocks: tuple[tuple[str, AnnotatedCodeBlock], ...]


@dataclass(frozen=True, slots=True)
class _Fence:
    start: int
    end: int
    indent: str
    language: str
    special: bool


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate mapping keys."""


def _construct_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _line_text(line: str) -> str:
    return line.rstrip("\r\n")


def _language(info: str) -> str:
    info = info.strip()
    if not info:
        return ""
    language = info.split(None, 1)[0]
    if language.startswith("{"):
        match = _ATTR_LANGUAGE_RE.search(info)
        language = match.group(1) if match else ""
    return language if _LANGUAGE_RE.match(language) else ""


def _fence_open(line: str) -> tuple[str, str, str] | None:
    match = _FENCE_OPEN_RE.match(_line_text(line))
    if not match:
        return None
    return match.group("indent"), match.group("marker"), _language(match.group("info"))


def _fence_close(line: str, marker: str) -> bool:
    pattern = rf"^[ \t]{{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$"
    return bool(re.match(pattern, _line_text(line)))


def _scan(lines: list[str]) -> tuple[list[_Fence], list[tuple[int, int, str]]]:
    """Find every fenced block and every standalone HTML comment."""

    fences: list[_Fence] = []
    comments: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        opened = _fence_open(lines[index])
        if opened:
            indent, marker, language = opened
            end = index
            for candidate in range(index + 1, len(lines)):
                if _fence_close(lines[candidate], marker):
                    end = candidate
                    break
            if end == index:
                # An unclosed fence owns the rest of the document, so a
                # comment inside it is displayed code, not metadata.
                break
            fences.append(
                _Fence(
                    start=index,
                    end=end,
                    indent=indent,
                    language=language,
                    special=(marker == "```" and language.lower() in SPECIAL_FENCE_LANGUAGES),
                )
            )
            index = end + 1
            continue

        if _COMMENT_OPEN_RE.match(_line_text(lines[index])):
            close = None
            for candidate in range(index + 1, len(lines)):
                if _COMMENT_CLOSE_RE.match(_line_text(lines[candidate])):
                    close = candidate
                    break
            if close is not None:
                comments.append((index, close, "".join(lines[index + 1 : close])))
                index = close + 1
                continue
            if _looks_like_payload("".join(lines[index + 1 :])):
                raise CodeAnnotationError(
                    f"unclosed structured code metadata near source line {index + 1}: "
                    "expected a standalone --> line"
                )
        elif "<!--" in lines[index] and _RESERVED_KEY_RE.search(lines[index]):
            raise CodeAnnotationError(
                f"structured code metadata near source line {index + 1} must use "
                "a standalone multi-line HTML comment"
            )
        index += 1
    return fences, comments


def _looks_like_payload(payload: str) -> bool:
    """Decide whether a comment is claiming to be annotation metadata."""

    try:
        root = yaml.compose(payload, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return _malformed_payload_has_root_key(payload)
    if not isinstance(root, MappingNode):
        return False
    keys = {key_node.value for key_node, _value in root.value if isinstance(key_node, ScalarNode)}
    return bool(keys & _RESERVED_KEYS)


def _malformed_payload_has_root_key(payload: str) -> bool:
    """Keep malformed annotation YAML visible to validation.

    Composition is authoritative for valid YAML. When composition fails, scan
    the key tokens produced before the syntax error and treat a reserved key at
    the document's shallowest mapping indentation as a claim. This preserves a
    useful error for a broken payload without promoting a nested ``structured``
    key in an unrelated comment.
    """

    keys: list[tuple[int, str]] = []
    pending_column = None
    try:
        for token in yaml.scan(payload, Loader=yaml.SafeLoader):
            if isinstance(token, KeyToken):
                pending_column = token.start_mark.column
            elif pending_column is not None:
                if isinstance(token, ScalarToken):
                    keys.append((pending_column, token.value))
                    pending_column = None
                elif not isinstance(token, TagToken | AnchorToken):
                    pending_column = None
    except yaml.YAMLError:
        pass
    if not keys:
        return False
    root_column = min(column for column, _key in keys)
    return any(column == root_column and key in _RESERVED_KEYS for column, key in keys)


def _parse_payload(payload: str, source_line: int) -> tuple[CodeAnnotation, ...]:
    loader = _StrictSafeLoader(payload)
    try:
        data = loader.get_single_data()
    except yaml.YAMLError as error:
        raise CodeAnnotationError(
            f"invalid YAML near source line {source_line}: {error}"
        ) from error
    finally:
        loader.dispose()

    if not isinstance(data, dict):
        raise CodeAnnotationError(f"payload near source line {source_line} must be a mapping")
    if set(data) != _RESERVED_KEYS:
        details = []
        missing = sorted(str(key) for key in _RESERVED_KEYS - set(data))
        unknown = sorted(str(key) for key in set(data) - _RESERVED_KEYS)
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown key(s): {', '.join(unknown)}")
        raise CodeAnnotationError(
            f"invalid payload near source line {source_line}: {'; '.join(details)}"
        )
    if data["structured"] is not True:
        raise CodeAnnotationError(
            f"payload near source line {source_line}: structured must be true"
        )

    raw_annotations = data["code_annotations"]
    if not isinstance(raw_annotations, list) or not raw_annotations:
        raise CodeAnnotationError(
            f"payload near source line {source_line}: code_annotations must be a non-empty sequence"
        )

    _reject_unquoted_ranges(payload, source_line)

    annotations = []
    for index, raw in enumerate(raw_annotations, start=1):
        where = f"payload near source line {source_line}, annotation {index}"
        if not isinstance(raw, dict):
            raise CodeAnnotationError(f"{where}: item must be a mapping")
        keys = set(raw)
        unknown = sorted(str(key) for key in keys - _ANNOTATION_KEYS)
        if unknown:
            raise CodeAnnotationError(f"{where}: unknown key(s): {', '.join(unknown)}")
        selectors = keys & {"line", "lines"}
        if selectors not in ({"line"}, {"lines"}):
            raise CodeAnnotationError(f"{where}: use exactly one of line or lines")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise CodeAnnotationError(f"{where}: text must be a non-empty string")
        text = _WHITESPACE_RE.sub(" ", text).strip()

        if "line" in raw:
            line = raw["line"]
            if isinstance(line, bool) or not isinstance(line, int) or line < 1:
                raise CodeAnnotationError(f"{where}: line must be a positive integer")
            annotations.append(CodeAnnotation(line, line, text))
            continue

        value = raw["lines"]
        match = _LINES_RE.match(value) if isinstance(value, str) else None
        if not match:
            raise CodeAnnotationError(f"{where}: lines must be a quoted positive start-end range")
        start = int(match.group("start"))
        end = int(match.group("end"))
        if start >= end:
            raise CodeAnnotationError(f"{where}: range start must be less than range end")
        annotations.append(CodeAnnotation(start, end, text))
    return tuple(annotations)


def _reject_unquoted_ranges(payload: str, source_line: int) -> None:
    """Reject plain-style ``lines`` scalars such as ``lines: 2-4``.

    An unquoted range is a YAML string too, so the value alone cannot tell the
    author's intent apart from a typo. Requiring quotes keeps the authored form
    unambiguous.
    """

    root = yaml.compose(payload, Loader=yaml.SafeLoader)
    if not isinstance(root, MappingNode):
        return
    sequence = None
    for key_node, value_node in root.value:
        if isinstance(key_node, ScalarNode) and key_node.value == "code_annotations":
            sequence = value_node
            break
    if not isinstance(sequence, SequenceNode):
        return
    for index, item in enumerate(sequence.value, start=1):
        if not isinstance(item, MappingNode):
            continue
        for key_node, value_node in item.value:
            if key_node.value != "lines" or not isinstance(key_node, ScalarNode):
                continue
            if not isinstance(value_node, ScalarNode) or value_node.style not in {"'", '"'}:
                raise CodeAnnotationError(
                    f"payload near source line {source_line}, annotation {index}: "
                    "lines must be a quoted positive start-end range"
                )


def _preceding_fence(comment_start: int, fences: list[_Fence]) -> _Fence | None:
    return next((fence for fence in reversed(fences) if fence.end < comment_start), None)


def _attached_fence(comment_start: int, fences: list[_Fence], lines: list[str]) -> _Fence | None:
    """The fence a payload belongs to: the previous one, with only blanks between."""

    fence = _preceding_fence(comment_start, fences)
    if fence is None:
        return None
    if "".join(lines[fence.end + 1 : comment_start]).strip():
        return None
    return fence


def _validate_ranges(
    annotations: tuple[CodeAnnotation, ...],
    fence: _Fence,
    source_line: int,
) -> None:
    code_line_count = fence.end - fence.start - 1
    occupied: set[int] = set()
    for annotation in annotations:
        if annotation.end > code_line_count:
            raise CodeAnnotationError(
                f"annotation near source line {source_line} points to line {annotation.end}, "
                f"but the code block has {code_line_count} visible lines"
            )
        current = set(range(annotation.start, annotation.end + 1))
        if occupied & current:
            raise CodeAnnotationError(
                f"annotation near source line {source_line} overlaps or repeats "
                "another annotation range"
            )
        occupied.update(current)


def _block(fence: _Fence, lines: list[str], annotations: tuple[CodeAnnotation, ...]):
    highlighted = {
        number
        for annotation in annotations
        for number in range(annotation.start, annotation.end + 1)
    }
    code_lines = tuple(
        CodeLine(number=number, text=_line_text(line), is_highlighted=number in highlighted)
        for number, line in enumerate(lines[fence.start + 1 : fence.end], start=1)
    )
    return AnnotatedCodeBlock(language=fence.language, lines=code_lines, annotations=annotations)


def _collect(body: str) -> tuple[list[str], list[_Fence], dict[int, AnnotatedCodeBlock], set[int]]:
    """Parse ``body`` once into fences, blocks keyed by fence index, and dead lines."""

    lines = body.splitlines(keepends=True)
    fences, comments = _scan(lines)
    blocks: dict[int, AnnotatedCodeBlock] = {}
    dead_lines: set[int] = set()
    claimed_comment_ends: dict[int, int] = {}

    for comment_start, comment_end, payload in comments:
        if not _looks_like_payload(payload):
            continue
        source_line = comment_start + 1
        annotations = _parse_payload(payload, source_line)

        previous = _preceding_fence(comment_start, fences)
        previous_index = fences.index(previous) if previous is not None else None
        claimed_end = claimed_comment_ends.get(previous_index)
        if claimed_end is not None and not "".join(lines[claimed_end + 1 : comment_start]).strip():
            raise CodeAnnotationError(
                f"duplicate structured code metadata near source line {source_line}: "
                "one payload per code block is allowed"
            )

        fence = _attached_fence(comment_start, fences, lines)
        if fence is None:
            raise CodeAnnotationError(
                f"orphaned structured code metadata near source line {source_line}: "
                "it must immediately follow a code fence"
            )
        if fence.special:
            raise CodeAnnotationError(
                f"structured code metadata near source line {source_line}: "
                "special fences cannot have annotations"
            )
        _validate_ranges(annotations, fence, source_line)
        fence_index = fences.index(fence)
        if fence_index in blocks:
            raise CodeAnnotationError(
                f"duplicate structured code metadata near source line {source_line}: "
                "one payload per code block is allowed"
            )
        blocks[fence_index] = _block(fence, lines, annotations)
        claimed_comment_ends[fence_index] = comment_end
        dead_lines.update(range(comment_start, comment_end + 1))

    return lines, fences, blocks, dead_lines


def parse_annotated_body(body: str) -> ParsedUnitBody:
    """Validate a unit body and strip its annotation payloads from the markdown.

    Raises :class:`CodeAnnotationError` when a payload claims to be annotation
    metadata but does not satisfy the contract. Fail closed: a malformed
    payload must stop an import rather than render as prose.
    """

    if not body:
        return ParsedUnitBody("", ())

    lines, fences, blocks, dead_lines = _collect(body)
    ordered = tuple(blocks.get(index) for index in range(len(fences)))
    if not dead_lines:
        return ParsedUnitBody(body, ordered)
    markdown = "".join(line for index, line in enumerate(lines) if index not in dead_lines)
    return ParsedUnitBody(markdown, ordered)


def build_render_plan(body: str) -> RenderPlan:
    """Parse ``body`` and swap each annotated fence for an opaque token.

    The token is a bare alphanumeric word on its own line, so a markdown
    renderer emits it as a plain paragraph the caller can substitute exactly.
    The fence's own indentation is preserved, which keeps a block nested in a
    list item inside that list item.
    """

    if not body:
        return RenderPlan("", ())

    lines, fences, blocks, dead_lines = _collect(body)
    if not blocks:
        markdown = "".join(line for index, line in enumerate(lines) if index not in dead_lines)
        return RenderPlan(markdown, ())

    tokens: list[tuple[str, AnnotatedCodeBlock]] = []
    replacements: dict[int, str] = {}
    for fence_index, block in sorted(blocks.items()):
        fence = fences[fence_index]
        token = f"cbcodeannotations{uuid.uuid4().hex}"
        tokens.append((token, block))
        replacements[fence.start] = f"\n\n{fence.indent}{token}\n\n"
        dead_lines.update(range(fence.start + 1, fence.end + 1))

    rendered_lines = []
    for index, line in enumerate(lines):
        if index in replacements:
            rendered_lines.append(replacements[index])
        elif index not in dead_lines:
            rendered_lines.append(line)
    return RenderPlan("".join(rendered_lines), tuple(tokens))


def validate_annotated_body(body: str, where: str) -> None:
    """Raise ``CodeAnnotationError`` prefixed with ``where`` if ``body`` is invalid."""

    try:
        parse_annotated_body(body)
    except CodeAnnotationError as error:
        raise CodeAnnotationError(f"{where}: {error}") from None
