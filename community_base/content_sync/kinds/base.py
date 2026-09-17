"""Schema types for the content format: keys, parts, kinds and their problems.

`FORMAT.md` is the normative text; this module is the machine-readable half of
sections 3.3 and 3.8. Nothing here touches Django, the database or a site: the
validator (`community_base.content_sync.check`) and, later, the parser toolkit
both read these declarations.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from community_base.curriculum.source import ACCESS_NAMES

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KIND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
ORDER_PREFIX_PATTERN = re.compile(r"^(\d{2,3})-(?=.)")
DATE_PREFIX_PATTERN = re.compile(r"^(?:\d{4}|\d{2})-\d{2}-\d{2}-")
HASHTAG_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
TIMESTAMP_PATTERN = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")
TYPED_REFERENCE_PATTERN = re.compile(r"^([a-z][a-z0-9_]*):(?!//)(\S+)$")
REFERENCE_TARGET_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKDOWN_IN_TEXT_PATTERN = re.compile(r"\]\(|`|\*\*|^\s*[-*]\s", re.MULTILINE)

MAX_SLUG_LENGTH = 100
MAX_ASSET_BYTES = 16 * 1024 * 1024
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf")

SHAPE_DOCUMENT = "document"
SHAPE_MANIFEST = "manifest"
SHAPE_TREE = "tree"
SHAPE_DATA = "data"
SHAPES = (SHAPE_DOCUMENT, SHAPE_MANIFEST, SHAPE_TREE, SHAPE_DATA)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

STATUS_CHOICES = ("draft", "published")


@dataclass(frozen=True, slots=True)
class Problem:
    """One rule violation inside one file, before the file path is known."""

    pointer: str
    rule: str
    message: str
    severity: str = SEVERITY_ERROR
    line: int | None = None


@dataclass(frozen=True, slots=True)
class KeySpec:
    """One declared key of a kind or of the core."""

    type: str
    required: bool = False
    default: Any = None
    max_length: int | None = None
    choices: tuple[str, ...] | None = None
    reference_kind: str | None = None
    item_keys: Mapping[str, KeySpec] | None = None
    rule: str = "3.8"


@dataclass(frozen=True, slots=True)
class PartSpec:
    """One file schema inside a kind.

    A simple kind has exactly one part. A composite kind such as `course` has
    one per file shape it owns: the course manifest, a module manifest, a unit
    document, a cohort manifest and a homework manifest.
    """

    name: str
    shape: str
    keys: Mapping[str, KeySpec] = field(default_factory=dict)
    requires_date: bool = False
    core_keys: bool = True
    allow_unknown: bool = False


@dataclass(frozen=True, slots=True)
class RawItem:
    """A file a layout recognised as an item, before it is read."""

    part: str
    path: str
    container: str
    name: str
    parent: str | None = None
    contributes_slug: bool = True


@dataclass(frozen=True, slots=True)
class DirNode:
    """A visible directory of a repository: ignored and hidden names are gone."""

    path: str
    files: tuple[str, ...] = ()
    dirs: tuple[DirNode, ...] = ()

    def child(self, name: str) -> DirNode | None:
        for node in self.dirs:
            if node.path.rsplit("/", 1)[-1] == name:
                return node
        return None

    def has(self, name: str) -> bool:
        return name in self.files

    def joined(self, name: str) -> str:
        return f"{self.path}/{name}" if self.path else name


class Layout:
    """How the files under a collection path become items.

    A layout is pure: it reads a `DirNode` tree and returns items and problems.
    It never opens a file, so layout rules are testable without fixtures on
    disk and a site can reuse one of the package layouts for its own kind.
    """

    def walk(self, root: DirNode) -> tuple[list[RawItem], list[tuple[str, Problem]]]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class KindSpec:
    """A content kind: file shape, layout, keys, dependencies and route."""

    name: str
    shape: str
    layout: Layout
    keys: Mapping[str, KeySpec] = field(default_factory=dict)
    asset_keys: tuple[str, ...] = ()
    requires_date: bool = False
    depends_on: tuple[str, ...] | None = None
    route: Callable[[str], str] | None = None
    parts: Mapping[str, PartSpec] = field(default_factory=dict)
    core_keys: bool = True
    allow_unknown: bool = False

    @property
    def item_parts(self) -> Mapping[str, PartSpec]:
        if self.parts:
            return self.parts
        return {
            self.name: PartSpec(
                name=self.name,
                shape=self.shape,
                keys=self.keys,
                requires_date=self.requires_date,
                core_keys=self.core_keys,
                allow_unknown=self.allow_unknown,
            )
        }

    def part(self, name: str) -> PartSpec:
        try:
            return self.item_parts[name]
        except KeyError:
            raise LookupError(f"Kind {self.name} has no part {name}") from None

    def asset_key_names(self, part: PartSpec) -> tuple[str, ...]:
        names = {"image", *self.asset_keys}
        names.update(name for name, spec in part.keys.items() if spec.type == "asset")
        return tuple(sorted(names))

    @property
    def dependencies(self) -> tuple[str, ...]:
        """The kinds whose rows must exist before this kind's references resolve.

        An explicit `depends_on` wins. Otherwise the fixed kinds named by the
        reference keys of every part are the dependency set, so `article`,
        whose `authors` key is a person reference, depends on `person` without
        declaring it.
        """

        if self.depends_on is not None:
            return tuple(dict.fromkeys(self.depends_on))
        found: list[str] = []
        for part in self.item_parts.values():
            for spec in part.keys.values():
                found.extend(_reference_kinds(spec))
        return tuple(sorted(set(found) - {self.name}))


def _reference_kinds(spec: KeySpec) -> list[str]:
    found: list[str] = []
    if spec.reference_kind:
        found.append(spec.reference_kind)
    for nested in (spec.item_keys or {}).values():
        found.extend(_reference_kinds(nested))
    return found


CORE_KEYS: Mapping[str, KeySpec] = {
    "content_id": KeySpec("uuid", required=True, rule="3.3"),
    "title": KeySpec("string", required=True, max_length=300, rule="3.3"),
    "slug": KeySpec("slug", rule="3.3"),
    "summary": KeySpec("text", max_length=500, rule="3.3"),
    "status": KeySpec("choice", choices=STATUS_CHOICES, default="published", rule="3.3"),
    "required_level": KeySpec("level", rule="3.3"),
    "sort_order": KeySpec("integer", rule="3.3"),
    "tags": KeySpec("slug_list", rule="3.3"),
    "image": KeySpec("asset", rule="3.3"),
    "date": KeySpec("date", rule="3.3"),
    "extra": KeySpec("mapping", rule="3.3"),
}


def effective_keys(part: PartSpec) -> Mapping[str, KeySpec]:
    """Core keys plus the part's own, which never collide (see register_kind)."""

    if not part.core_keys:
        return dict(part.keys)
    return {**CORE_KEYS, **part.keys}


def check_item_keys(data: Mapping[str, Any], part: PartSpec) -> list[Problem]:
    """Every key rule of sections 3.3 and 3.8 for one parsed file."""

    problems: list[Problem] = []
    keys = effective_keys(part)
    for name, spec in keys.items():
        pointer = f"/{name}"
        if name not in data or data[name] is None:
            if name == "date":
                if part.requires_date:
                    problems.append(
                        Problem(pointer, "3.3", "required key date is missing", line=None)
                    )
                continue
            if spec.required:
                problems.append(Problem(pointer, spec.rule, f"required key {name} is missing"))
            continue
        if name == "date" and not part.requires_date and part.core_keys:
            problems.append(
                Problem(
                    pointer,
                    "3.3",
                    "date is forbidden on this kind; chronology belongs to kinds that declare it",
                )
            )
            continue
        problems.extend(check_value(data[name], spec, pointer))
    if not part.allow_unknown:
        for name in data:
            if name not in keys:
                problems.append(Problem(f"/{name}", "3.3", f"unknown top-level key: {name}"))
    return problems


def check_value(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    checker = _CHECKERS.get(spec.type)
    if checker is None:  # pragma: no cover -- guarded by register_kind
        raise ValueError(f"Unknown key type: {spec.type}")
    return checker(value, spec, pointer)


def _text_value(value: Any, spec: KeySpec, pointer: str) -> list[Problem] | str:
    if not isinstance(value, str):
        return [Problem(pointer, spec.rule, f"must be a string, found {_type_name(value)}")]
    if spec.max_length is not None and len(value) > spec.max_length:
        return [
            Problem(
                pointer,
                spec.rule,
                f"must be at most {spec.max_length} characters, found {len(value)}",
            )
        ]
    return value


def _check_string(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    checked = _text_value(value, spec, pointer)
    if isinstance(checked, list):
        return checked
    if spec.required and not checked.strip():
        return [Problem(pointer, spec.rule, "must not be empty")]
    return []


def _check_text(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    checked = _text_value(value, spec, pointer)
    if isinstance(checked, list):
        return checked
    problems: list[Problem] = []
    if "\n" in checked.strip():
        problems.append(Problem(pointer, spec.rule, "must be one line of plain text"))
    if MARKDOWN_IN_TEXT_PATTERN.search(checked):
        problems.append(
            Problem(pointer, spec.rule, "must be plain text, not markdown", SEVERITY_WARNING)
        )
    return problems


def _check_markdown(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    checked = _text_value(value, spec, pointer)
    return checked if isinstance(checked, list) else []


def _check_uuid(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not isinstance(value, str):
        return [
            Problem(
                pointer,
                spec.rule,
                f"must be a quoted UUID string, found {_type_name(value)}",
            )
        ]
    try:
        uuid.UUID(value)
    except ValueError:
        return [Problem(pointer, spec.rule, f"must be a UUID, found {value!r}")]
    return []


def _check_slug(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not isinstance(value, str):
        return [Problem(pointer, spec.rule, f"must be a slug string, found {_type_name(value)}")]
    if len(value) > MAX_SLUG_LENGTH:
        return [Problem(pointer, spec.rule, f"slug is longer than {MAX_SLUG_LENGTH} characters")]
    if not SLUG_PATTERN.match(value):
        return [Problem(pointer, spec.rule, f"must match {SLUG_PATTERN.pattern}, found {value!r}")]
    return []


def _check_slug_list(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not _is_sequence(value):
        return [Problem(pointer, spec.rule, f"must be a list, found {_type_name(value)}")]
    problems: list[Problem] = []
    for index, item in enumerate(value):
        problems.extend(_check_slug(item, spec, f"{pointer}/{index}"))
    return problems


def _check_integer(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if isinstance(value, bool) or not isinstance(value, int):
        return [Problem(pointer, spec.rule, f"must be an integer, found {_type_name(value)}")]
    return []


def _check_boolean(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not isinstance(value, bool):
        return [Problem(pointer, spec.rule, f"must be true or false, found {_type_name(value)}")]
    return []


def _check_date(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if isinstance(value, dt.datetime):
        return [Problem(pointer, spec.rule, "must be a date, not a datetime")]
    if isinstance(value, dt.date):
        return []
    if isinstance(value, str) and ISO_DATE_PATTERN.match(value):
        try:
            dt.date.fromisoformat(value)
        except ValueError:
            return [Problem(pointer, spec.rule, f"is not a calendar date: {value!r}")]
        return []
    return [Problem(pointer, spec.rule, f"must be an ISO date YYYY-MM-DD, found {value!r}")]


def _check_datetime(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if isinstance(value, dt.datetime):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = dt.datetime.fromisoformat(value)
        except ValueError:
            return [Problem(pointer, spec.rule, f"must be an ISO datetime, found {value!r}")]
    else:
        return [Problem(pointer, spec.rule, f"must be an ISO datetime, found {_type_name(value)}")]
    if candidate.tzinfo is None:
        return [Problem(pointer, spec.rule, "must carry a UTC offset")]
    return []


def _check_url(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    checked = _text_value(value, spec, pointer)
    if isinstance(checked, list):
        return checked
    if not checked:
        return []
    if not checked.startswith("https://"):
        return [Problem(pointer, spec.rule, f"must be an https URL, found {checked!r}")]
    return []


def _check_level(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if isinstance(value, bool):
        return [Problem(pointer, spec.rule, "must be an access level, found a boolean")]
    if isinstance(value, int):
        if value < 0:
            return [Problem(pointer, spec.rule, "must not be negative")]
        return []
    if isinstance(value, str) and value in ACCESS_NAMES:
        return []
    names = ", ".join(sorted(ACCESS_NAMES))
    return [Problem(pointer, spec.rule, f"must be an integer or one of {names}, found {value!r}")]


def _check_mapping(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not isinstance(value, Mapping):
        return [Problem(pointer, spec.rule, f"must be a mapping, found {_type_name(value)}")]
    return []


def _check_list(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not _is_sequence(value):
        return [Problem(pointer, spec.rule, f"must be a list, found {_type_name(value)}")]
    return []


def _check_choice(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    choices = spec.choices or ()
    if value not in choices:
        allowed = ", ".join(str(choice) for choice in choices)
        return [Problem(pointer, spec.rule, f"must be one of {allowed}, found {value!r}")]
    return []


def _check_hashtag(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    checked = _text_value(value, spec, pointer)
    if isinstance(checked, list):
        return checked
    if checked and not HASHTAG_PATTERN.match(checked):
        return [Problem(pointer, spec.rule, f"must be {HASHTAG_PATTERN.pattern} without #")]
    return []


def _check_timestamp(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.match(value):
        return [Problem(pointer, spec.rule, f"must be MM:SS or H:MM:SS, found {value!r}")]
    return []


def _check_asset(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    """The shape half of section 3.6; existence is checked against the tree."""

    checked = _text_value(value, spec, pointer)
    if isinstance(checked, list):
        return checked
    return check_asset_reference(checked, pointer)


def check_asset_reference(value: str, pointer: str, line: int | None = None) -> list[Problem]:
    reference = value.strip()
    if not reference:
        return []
    if reference.startswith("https://"):
        return []
    if reference.startswith("http://"):
        return [Problem(pointer, "3.6", "http:// references are not allowed", line=line)]
    if reference.startswith("data:"):
        return [Problem(pointer, "3.6", "data: references are not allowed", line=line)]
    if reference.startswith("/"):
        return [
            Problem(
                pointer, "3.6", f"must be a relative path, found absolute {reference!r}", line=line
            )
        ]
    if "{%" in reference or "{{" in reference:
        return [Problem(pointer, "3.6", "Liquid is not part of the format", line=line)]
    if reference.startswith("{IMAGE:"):
        return [Problem(pointer, "3.6", "{IMAGE:id} tokens are not part of the format", line=line)]
    if "://" in reference:
        scheme = reference.split("://", 1)[0]
        return [Problem(pointer, "3.6", f"{scheme}:// references are not allowed", line=line)]
    return []


def _check_reference(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not isinstance(value, str):
        return [
            Problem(pointer, spec.rule, f"must be a reference string, found {_type_name(value)}")
        ]
    return check_reference_shape(value, pointer, spec.reference_kind, spec.rule)


def check_reference_shape(
    value: str, pointer: str, fixed_kind: str | None, rule: str = "3.7"
) -> list[Problem]:
    reference = value.strip()
    if not reference:
        return [Problem(pointer, rule, "reference must not be empty")]
    if reference.startswith("[[") or reference.endswith("]]"):
        return [Problem(pointer, rule, "[[wikilinks]] are not part of the format")]
    match = TYPED_REFERENCE_PATTERN.match(reference)
    if match is None:
        if fixed_kind is None:
            return [
                Problem(
                    pointer,
                    rule,
                    f"must be kind:target, found {reference!r}",
                )
            ]
        target = reference
    else:
        target = match.group(2)
    if not REFERENCE_TARGET_PATTERN.match(target):
        return [Problem(pointer, rule, f"reference target is not a slug or path: {target!r}")]
    return []


def _check_reference_list(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not _is_sequence(value):
        return [Problem(pointer, spec.rule, f"must be a list, found {_type_name(value)}")]
    problems: list[Problem] = []
    for index, item in enumerate(value):
        problems.extend(_check_reference(item, spec, f"{pointer}/{index}"))
    return problems


def _check_object_list(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    if not _is_sequence(value):
        return [Problem(pointer, spec.rule, f"must be a list, found {_type_name(value)}")]
    problems: list[Problem] = []
    item_keys = spec.item_keys or {}
    for index, item in enumerate(value):
        item_pointer = f"{pointer}/{index}"
        if not isinstance(item, Mapping):
            problems.append(
                Problem(item_pointer, spec.rule, f"must be a mapping, found {_type_name(item)}")
            )
            continue
        for name, nested in item_keys.items():
            nested_pointer = f"{item_pointer}/{name}"
            if name not in item or item[name] is None:
                if nested.required:
                    problems.append(
                        Problem(nested_pointer, spec.rule, f"required key {name} is missing")
                    )
                continue
            problems.extend(check_value(item[name], nested, nested_pointer))
        for name in item:
            if item_keys and name not in item_keys:
                problems.append(
                    Problem(f"{item_pointer}/{name}", spec.rule, f"unknown key: {name}")
                )
    return problems


def _check_any(value: Any, spec: KeySpec, pointer: str) -> list[Problem]:
    return []


_CHECKERS: Mapping[str, Callable[[Any, KeySpec, str], list[Problem]]] = {
    "any": _check_any,
    "asset": _check_asset,
    "boolean": _check_boolean,
    "choice": _check_choice,
    "date": _check_date,
    "datetime": _check_datetime,
    "hashtag": _check_hashtag,
    "integer": _check_integer,
    "level": _check_level,
    "list": _check_list,
    "mapping": _check_mapping,
    "markdown": _check_markdown,
    "object_list": _check_object_list,
    "reference": _check_reference,
    "reference_list": _check_reference_list,
    "slug": _check_slug,
    "slug_list": _check_slug_list,
    "string": _check_string,
    "text": _check_text,
    "timestamp": _check_timestamp,
    "url": _check_url,
    "uuid": _check_uuid,
}

KEY_TYPES = tuple(sorted(_CHECKERS))


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _type_name(value: Any) -> str:
    if value is None:
        return "nothing"
    return type(value).__name__


def split_order_prefix(name: str) -> tuple[int | None, str]:
    """The `NN-` ordering prefix of a file or directory name, and the rest."""

    match = ORDER_PREFIX_PATTERN.match(name)
    if match is None:
        return None, name
    return int(match.group(1)), name[match.end() :]


def slug_from_name(name: str) -> str:
    """The default slug of a file or directory name (section 3.4)."""

    stem = name
    for suffix in (".md", ".yaml", ".yml", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return split_order_prefix(stem)[1]


def is_asset_name(name: str) -> bool:
    return name.lower().endswith(ASSET_SUFFIXES)
