"""`check_content`: a content repository against `FORMAT.md`, with no database.

One implementation, two entry points (specification section 3.10):

    uv run python -m community_base.content_sync.check <path>
    uv run python manage.py check_content <path>

Both call :func:`run_check`, which writes the report and returns the number of
errors. The module entry point turns that into an exit code and the management
command turns it into a `CommandError`; neither owns a rule of its own.

Every diagnostic carries the repository-relative path of the file, a YAML
pointer into that file (`/` names the file as a whole) and the number of the
rule in `FORMAT.md` it enforces.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from community_base.content_sync.kinds import (
    ASSET_SUFFIXES,
    MAX_ASSET_BYTES,
    DirNode,
    KindSpec,
    PartSpec,
    Problem,
    RawItem,
    check_item_keys,
    get_kind,
    is_registered,
    kinds,
    slug_from_name,
)
from community_base.content_sync.kinds.base import (
    DATE_PREFIX_PATTERN,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SHAPE_DATA,
    SLUG_PATTERN,
    TYPED_REFERENCE_PATTERN,
    check_asset_reference,
)

MANIFEST_NAME = "content.yaml"
SCHEMA_VERSION = 1
WHOLE_FILE = "/"

MANIFEST_KEYS = ("schema_version", "collections", "ignore", "strict_references", "theme_pairs")
EXTERNAL_SCHEMES = ("http", "https", "mailto", "tel", "ftp")

FENCE_PATTERN = re.compile(r"^(\s*)(```+|~~~+)\s*(\S*)")
INLINE_CODE_PATTERN = re.compile(r"`[^`]*`")
LINK_PATTERN = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_IMG_PATTERN = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
LIQUID_PATTERN = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")
KRAMDOWN_PATTERN = re.compile(r"\{:\s*[.#][^}]*\}")
WIKILINK_PATTERN = re.compile(r"\[\[[^\]]+\]\]")
IMAGE_TOKEN_PATTERN = re.compile(r"\{IMAGE:[^}]*\}")
STRIKETHROUGH_PATTERN = re.compile(r"~~[^~\s][^~]*~~")
RAW_HTML_PATTERN = re.compile(r"<\s*(script|style|iframe)\b", re.IGNORECASE)
STYLE_ATTRIBUTE_PATTERN = re.compile(r"<[^>]*\sstyle\s*=", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FRONT_MATTER_FENCE = "---"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One rule violation, located."""

    path: str
    pointer: str
    rule: str
    message: str
    severity: str = SEVERITY_ERROR
    line: int | None = None

    def render(self) -> str:
        line = f":{self.line}" if self.line else ""
        marker = "" if self.severity == SEVERITY_ERROR else "warning: "
        return f"{self.path}{line}:{self.pointer}: [{self.rule}] {marker}{self.message}"

    @property
    def sort_key(self) -> tuple[str, int, str, str]:
        return (self.path, self.line or 0, self.pointer, self.rule)


@dataclass(frozen=True, slots=True)
class Collection:
    kind: KindSpec
    path: str
    index: int

    @property
    def pointer(self) -> str:
        return f"/collections/{self.index}"


@dataclass(slots=True)
class Item:
    collection: Collection
    part: PartSpec
    raw: RawItem
    data: dict[str, Any]
    body: str
    body_line: int
    slug: str
    is_document: bool = False
    path_key: str = ""


@dataclass(slots=True)
class Repository:
    """Everything read from disk once, so every check works on the same view."""

    root: Path
    tree: DirNode
    files: dict[str, Path] = field(default_factory=dict)
    ignored: set[str] = field(default_factory=set)


def check_repository(path: str | Path, *, kind_modules: Iterable[str] = ()) -> list[Diagnostic]:
    """Every diagnostic for the repository at `path`, sorted by location."""

    for module in kind_modules:
        importlib.import_module(module)
    root = Path(path)
    if not root.is_dir():
        return [Diagnostic(str(path), WHOLE_FILE, "3.1", "is not a directory")]
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return [
            Diagnostic(MANIFEST_NAME, WHOLE_FILE, "3.1", "every synced repository needs this file")
        ]
    data, problems = _load_yaml(manifest_path)
    if problems:
        return [_locate(MANIFEST_NAME, problem) for problem in problems]
    diagnostics: list[Diagnostic] = []
    collections = _check_manifest(data, diagnostics)
    repository = _read_repository(root, _ignore_patterns(data))
    items: list[Item] = []
    for collection in collections:
        items.extend(_check_collection(repository, collection, diagnostics))
    _check_identity(items, diagnostics)
    _check_bodies_and_references(repository, collections, items, data, diagnostics)
    return sorted(diagnostics, key=lambda diagnostic: diagnostic.sort_key)


def run_check(path: str | Path, *, stdout=None, kind_modules: Iterable[str] = ()) -> int:
    """Write the report for one repository and return the number of errors."""

    stream = sys.stdout if stdout is None else stdout
    diagnostics = check_repository(path, kind_modules=kind_modules)
    for diagnostic in diagnostics:
        stream.write(f"{diagnostic.render()}\n")
    errors = sum(1 for item in diagnostics if item.severity == SEVERITY_ERROR)
    warnings = len(diagnostics) - errors
    if errors or warnings:
        stream.write(f"{path}: {errors} error(s), {warnings} warning(s)\n")
    else:
        stream.write(f"{path}: matches the content format version 1\n")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m community_base.content_sync.check",
        description="Check a content repository against the DataTalks.Club content format.",
    )
    parser.add_argument("path", help="the repository to check")
    parser.add_argument(
        "--kinds",
        action="append",
        default=[],
        metavar="MODULE",
        help="import a module that registers site kinds before checking; repeatable",
    )
    options = parser.parse_args(argv)
    return 1 if run_check(options.path, kind_modules=options.kinds) else 0


# --- the repository manifest, section 3.1 ------------------------------------


def _check_manifest(data: Any, diagnostics: list[Diagnostic]) -> list[Collection]:
    if not isinstance(data, Mapping):
        diagnostics.append(
            Diagnostic(MANIFEST_NAME, WHOLE_FILE, "3.1", "top level must be a mapping")
        )
        return []
    for key in data:
        if key not in MANIFEST_KEYS:
            diagnostics.append(
                Diagnostic(MANIFEST_NAME, f"/{key}", "3.1", f"unknown top-level key: {key}")
            )
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        diagnostics.append(
            Diagnostic(
                MANIFEST_NAME,
                "/schema_version",
                "3.1",
                f"must be {SCHEMA_VERSION}, found {version!r}",
            )
        )
    for key in ("strict_references", "theme_pairs"):
        if key in data and not isinstance(data[key], bool):
            diagnostics.append(Diagnostic(MANIFEST_NAME, f"/{key}", "3.1", "must be true or false"))
    if "ignore" in data and not _is_string_list(data["ignore"]):
        diagnostics.append(Diagnostic(MANIFEST_NAME, "/ignore", "3.1", "must be a list of globs"))
    declared = data.get("collections")
    if not isinstance(declared, list) or not declared:
        diagnostics.append(
            Diagnostic(MANIFEST_NAME, "/collections", "3.1", "must list at least one collection")
        )
        return []
    collections: list[Collection] = []
    for index, entry in enumerate(declared):
        pointer = f"/collections/{index}"
        if not isinstance(entry, Mapping):
            diagnostics.append(Diagnostic(MANIFEST_NAME, pointer, "3.1", "must be a mapping"))
            continue
        for key in entry:
            if key not in ("kind", "path"):
                diagnostics.append(
                    Diagnostic(MANIFEST_NAME, f"{pointer}/{key}", "3.1", f"unknown key: {key}")
                )
        name = entry.get("kind")
        path = entry.get("path")
        if not isinstance(name, str) or not name:
            diagnostics.append(
                Diagnostic(MANIFEST_NAME, f"{pointer}/kind", "3.1", "must name a kind")
            )
            continue
        if not is_registered(name):
            registered = ", ".join(sorted(registered_name for registered_name, _ in kinds()))
            diagnostics.append(
                Diagnostic(
                    MANIFEST_NAME,
                    f"{pointer}/kind",
                    "3.1",
                    f"unknown kind: {name}; registered kinds are {registered}",
                )
            )
            continue
        if not isinstance(path, str) or not path:
            diagnostics.append(
                Diagnostic(
                    MANIFEST_NAME,
                    f"{pointer}/path",
                    "3.1",
                    "must be a repository-relative directory",
                )
            )
            continue
        normalised = _normalise_collection_path(path)
        if normalised is None:
            diagnostics.append(
                Diagnostic(
                    MANIFEST_NAME,
                    f"{pointer}/path",
                    "3.1",
                    f"must stay inside the repository, found {path!r}",
                )
            )
            continue
        collections.append(Collection(kind=get_kind(name), path=normalised, index=index))
    roots = [collection for collection in collections if collection.path == ""]
    if roots and len(collections) > 1:
        diagnostics.append(
            Diagnostic(
                MANIFEST_NAME,
                f"{roots[0].pointer}/path",
                "3.1",
                "a collection at '.' is the whole repository; no other collection may be declared",
            )
        )
    for collection in collections:
        for other in collections:
            if other is collection or not other.path or not collection.path:
                continue
            if collection.path.startswith(f"{other.path}/"):
                diagnostics.append(
                    Diagnostic(
                        MANIFEST_NAME,
                        f"{collection.pointer}/path",
                        "3.1",
                        f"collections never nest: {collection.path} is inside {other.path}",
                    )
                )
    return collections


def _normalise_collection_path(path: str) -> str | None:
    candidate = PurePosixPath(path.strip())
    if str(candidate) in (".", ""):
        return ""
    parts = [part for part in candidate.parts if part != "."]
    if any(part == ".." for part in parts) or candidate.is_absolute():
        return None
    return "/".join(parts)


def _ignore_patterns(data: Any) -> tuple[str, ...]:
    if not isinstance(data, Mapping):
        return ()
    patterns = data.get("ignore")
    if not _is_string_list(patterns):
        return ()
    return tuple(patterns)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


# --- reading the repository --------------------------------------------------


def _read_repository(root: Path, patterns: tuple[str, ...]) -> Repository:
    repository = Repository(root=root, tree=DirNode(path=""))
    repository.tree = _read_dir(root, "", patterns, repository)
    return repository


def _read_dir(directory: Path, rel: str, patterns: tuple[str, ...], repo: Repository) -> DirNode:
    files: list[str] = []
    dirs: list[DirNode] = []
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name.startswith((".", "_")) or entry.is_symlink():
            continue
        child_rel = f"{rel}/{entry.name}" if rel else entry.name
        if entry.is_dir():
            dirs.append(_read_dir(entry, child_rel, patterns, repo))
        elif entry.is_file():
            if _matches(child_rel, patterns):
                repo.ignored.add(child_rel)
                continue
            files.append(entry.name)
            repo.files[child_rel] = entry
    return DirNode(path=rel, files=tuple(files), dirs=tuple(dirs))


def _matches(rel: str, patterns: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(rel)
    return any(candidate.full_match(pattern) for pattern in patterns)


def _node_at(tree: DirNode, path: str) -> DirNode | None:
    node = tree
    if not path:
        return node
    for part in path.split("/"):
        node = node.child(part)
        if node is None:
            return None
    return node


# --- one collection ----------------------------------------------------------


def _check_collection(
    repository: Repository, collection: Collection, diagnostics: list[Diagnostic]
) -> list[Item]:
    node = _node_at(repository.tree, collection.path)
    if node is None:
        diagnostics.append(
            Diagnostic(
                MANIFEST_NAME,
                f"{collection.pointer}/path",
                "3.1",
                f"no such directory: {collection.path or '.'}",
            )
        )
        return []
    raw_items, problems = collection.kind.layout.walk(node)
    for path, problem in problems:
        diagnostics.append(_locate(path, problem))
    items: list[Item] = []
    by_path: dict[str, Item] = {}
    for raw in raw_items:
        item = _read_item(repository, collection, raw, diagnostics)
        if item is None:
            continue
        items.append(item)
        by_path[raw.path] = item
    for item in items:
        item.path_key = _path_key(item, by_path)
    _check_siblings(items, diagnostics)
    return items


def _read_item(
    repository: Repository,
    collection: Collection,
    raw: RawItem,
    diagnostics: list[Diagnostic],
) -> Item | None:
    part = collection.kind.part(raw.part)
    source = repository.files.get(raw.path)
    if source is None:  # pragma: no cover -- the tree named it a moment ago
        return None
    if _is_document(raw.path):
        data, body, body_line, problems = _load_document(source)
    else:
        data, problems = _load_yaml(source, require_mapping=part.shape != SHAPE_DATA)
        body, body_line = "", 0
    for problem in problems:
        diagnostics.append(_locate(raw.path, problem))
    if problems:
        return None
    if isinstance(data, Mapping):
        for problem in check_item_keys(data, part):
            diagnostics.append(_locate(raw.path, problem))
    elif part.shape != SHAPE_DATA:  # pragma: no cover -- _load_yaml refuses it
        return None
    else:
        data = {}
    diagnostics.extend(_check_name(raw))
    slug = _item_slug(collection, raw, data, diagnostics)
    if slug is None:
        return None
    return Item(
        collection=collection,
        part=part,
        raw=raw,
        data=dict(data),
        body=body,
        body_line=body_line,
        slug=slug,
        is_document=_is_document(raw.path),
    )


def _check_name(raw: RawItem) -> list[Diagnostic]:
    """Section 3.4 rules that read the file or directory name alone."""

    found: list[Diagnostic] = []
    name = raw.name
    if DATE_PREFIX_PATTERN.match(name):
        found.append(
            Diagnostic(
                raw.path,
                WHOLE_FILE,
                "3.4",
                f"names carry no date prefix; chronology is the date key: {name}",
            )
        )
    return found


def _item_slug(
    collection: Collection, raw: RawItem, data: Mapping[str, Any], diagnostics: list[Diagnostic]
) -> str | None:
    declared = data.get("slug")
    if isinstance(declared, str) and declared:
        return declared
    if collection.kind.shape == SHAPE_DATA:
        return slug_from_name(raw.name)
    candidate = slug_from_name(raw.name)
    if not candidate:
        diagnostics.append(
            Diagnostic(
                raw.path,
                "/slug",
                "3.3",
                "a collection at the repository root cannot take its slug from a name; declare one",
            )
        )
        return None
    if not SLUG_PATTERN.match(candidate):
        diagnostics.append(
            Diagnostic(
                raw.path,
                "/slug",
                "3.4",
                f"the name gives the slug {candidate!r}, which is not {SLUG_PATTERN.pattern};"
                " rename the file or declare a slug",
            )
        )
        return None
    return candidate


def _path_key(item: Item, by_path: Mapping[str, Item]) -> str:
    parts: list[str] = []
    current: Item | None = item
    seen: set[str] = set()
    while current is not None and current.raw.path not in seen:
        seen.add(current.raw.path)
        if current.raw.contributes_slug:
            parts.append(current.slug)
        parent = current.raw.parent
        current = by_path.get(parent) if parent else None
    return "/".join(reversed(parts))


def _check_siblings(items: list[Item], diagnostics: list[Diagnostic]) -> None:
    seen: dict[tuple[str, str, str], Item] = {}
    for item in items:
        key = (item.raw.part, item.raw.container, item.slug)
        first = seen.get(key)
        if first is not None:
            diagnostics.append(
                Diagnostic(
                    item.raw.path,
                    "/slug",
                    "3.4",
                    f"two siblings resolve to the slug {item.slug!r}; {first.raw.path} has it too",
                )
            )
            continue
        seen[key] = item


def _check_identity(items: list[Item], diagnostics: list[Diagnostic]) -> None:
    seen: dict[str, Item] = {}
    for item in items:
        content_id = item.data.get("content_id")
        if not isinstance(content_id, str):
            continue
        first = seen.get(content_id)
        if first is not None:
            diagnostics.append(
                Diagnostic(
                    item.raw.path,
                    "/content_id",
                    "3.4",
                    f"content_id {content_id} is already used by {first.raw.path}",
                )
            )
            continue
        seen[content_id] = item


# --- file shapes, section 3.2 ------------------------------------------------


def _load_yaml(path: Path, *, require_mapping: bool = True) -> tuple[Any, list[Problem]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, [Problem(WHOLE_FILE, "3.2", "must be UTF-8")]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return None, [Problem(WHOLE_FILE, "3.2", f"is not valid YAML: {_one_line(error)}")]
    if data is None:
        return None, [Problem(WHOLE_FILE, "3.2", "is empty")]
    if require_mapping and not isinstance(data, Mapping):
        return None, [Problem(WHOLE_FILE, "3.2", "top level must be a mapping")]
    return data, []


def _load_document(path: Path) -> tuple[Any, str, int, list[Problem]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, "", 0, [Problem(WHOLE_FILE, "3.2", "must be UTF-8")]
    if "\r\n" in text:
        return None, "", 0, [Problem(WHOLE_FILE, "3.2", "must use LF line endings")]
    lines = text.split("\n")
    if not lines or lines[0].strip() != FRONT_MATTER_FENCE:
        return (
            None,
            "",
            0,
            [Problem(WHOLE_FILE, "3.2", "a document starts with --- and YAML front matter")],
        )
    closing = None
    for number, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONT_MATTER_FENCE:
            closing = number
            break
    if closing is None:
        return None, "", 0, [Problem(WHOLE_FILE, "3.2", "front matter is never closed by ---")]
    try:
        data = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as error:
        return (
            None,
            "",
            0,
            [Problem(WHOLE_FILE, "3.2", f"front matter is not valid YAML: {_one_line(error)}")],
        )
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        return None, "", 0, [Problem(WHOLE_FILE, "3.2", "front matter must be a mapping")]
    body = "\n".join(lines[closing + 1 :])
    return data, body, closing + 1, []


def _one_line(error: Exception) -> str:
    return " ".join(str(error).split())


def _is_document(path: str) -> bool:
    """Section 3.2: a `.md` file is a document, everything else a manifest."""

    return path.endswith(".md")


# --- bodies: assets, references and the dialect ------------------------------


def _check_bodies_and_references(
    repository: Repository,
    collections: list[Collection],
    items: list[Item],
    manifest: Mapping[str, Any],
    diagnostics: list[Diagnostic],
) -> None:
    strict = manifest.get("strict_references", True) is not False
    severity = SEVERITY_ERROR if strict else SEVERITY_WARNING
    by_collection: dict[int, dict[str, Item]] = {}
    by_document: dict[str, Item] = {}
    for item in items:
        by_collection.setdefault(item.collection.index, {})[item.path_key] = item
        by_document[item.raw.path] = item
    declared_kinds = {collection.kind.name: collection for collection in collections}
    for item in items:
        _check_asset_keys(repository, item, diagnostics)
        if not item.is_document:
            continue
        headings = heading_ids(item.body)
        _check_dialect(item, headings, diagnostics)
        for reference in _references(item):
            _check_reference(
                repository,
                item,
                reference,
                by_collection,
                by_document,
                declared_kinds,
                severity,
                diagnostics,
            )
    for item in items:
        for pointer, value in _reference_key_values(item):
            _check_typed_reference(
                item, value, pointer, by_collection, declared_kinds, severity, diagnostics
            )


def _check_asset_keys(repository: Repository, item: Item, diagnostics: list[Diagnostic]) -> None:
    for name in item.collection.kind.asset_key_names(item.part):
        value = item.data.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        pointer = f"/{name}"
        problems = check_asset_reference(value, pointer)
        if problems:
            continue  # already reported by the key check
        if value.startswith("https://"):
            continue
        _check_asset_file(repository, item, value, pointer, None, diagnostics)


@dataclass(frozen=True, slots=True)
class Reference:
    destination: str
    line: int
    is_image: bool


def _references(item: Item) -> Iterator[Reference]:
    for number, line in _code_free_lines(item.body):
        for match in LINK_PATTERN.finditer(line):
            yield Reference(match.group(3), item.body_line + number, match.group(1) == "!")
        for match in HTML_IMG_PATTERN.finditer(line):
            yield Reference(match.group(1), item.body_line + number, True)


def _reference_key_values(item: Item) -> Iterator[tuple[str, str]]:
    keys = item.part.keys
    for name, spec in keys.items():
        if spec.type not in ("reference", "reference_list"):
            continue
        value = item.data.get(name)
        if isinstance(value, str):
            yield f"/{name}", _qualify(value, spec.reference_kind)
        elif isinstance(value, list):
            for index, entry in enumerate(value):
                if isinstance(entry, str):
                    yield f"/{name}/{index}", _qualify(entry, spec.reference_kind)


def _qualify(value: str, fixed_kind: str | None) -> str:
    if fixed_kind and not TYPED_REFERENCE_PATTERN.match(value.strip()):
        return f"{fixed_kind}:{value.strip()}"
    return value.strip()


def _check_reference(
    repository: Repository,
    item: Item,
    reference: Reference,
    by_collection: Mapping[int, Mapping[str, Item]],
    by_document: Mapping[str, Item],
    declared_kinds: Mapping[str, Collection],
    severity: str,
    diagnostics: list[Diagnostic],
) -> None:
    destination = reference.destination.strip()
    pointer = "/body"
    if not destination or destination.startswith("#"):
        return
    scheme = destination.split(":", 1)[0].lower() if ":" in destination else ""
    if scheme in EXTERNAL_SCHEMES or destination.startswith("//"):
        if reference.is_image:
            for problem in check_asset_reference(destination, pointer, reference.line):
                diagnostics.append(_locate(item.raw.path, problem))
        return
    if TYPED_REFERENCE_PATTERN.match(destination):
        _check_typed_reference(
            item,
            destination,
            pointer,
            by_collection,
            declared_kinds,
            severity,
            diagnostics,
            line=reference.line,
        )
        return
    problems = check_asset_reference(destination, pointer, reference.line)
    if problems:
        for problem in problems:
            diagnostics.append(_locate(item.raw.path, problem))
        return
    target, _, fragment = destination.partition("#")
    if not target:
        return
    resolved = _resolve_relative(item.raw.path, target)
    if resolved is None:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.6",
                f"reference leaves the repository: {destination}",
                line=reference.line,
            )
        )
        return
    if reference.is_image or resolved.lower().endswith(ASSET_SUFFIXES):
        _check_asset_file(repository, item, target, pointer, reference.line, diagnostics)
        return
    target_item = by_document.get(resolved)
    if target_item is None:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.7",
                f"relative link resolves to no document of this collection: {destination}",
                severity=severity,
                line=reference.line,
            )
        )
        return
    if target_item.collection.index != item.collection.index:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.7",
                f"a relative link stays in one collection; use a typed reference: {destination}",
                severity=severity,
                line=reference.line,
            )
        )
        return
    if fragment and fragment not in {heading[1] for heading in heading_ids(target_item.body)}:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.7",
                f"no heading {fragment!r} in {target_item.raw.path}",
                severity=severity,
                line=reference.line,
            )
        )


def _check_typed_reference(
    item: Item,
    destination: str,
    pointer: str,
    by_collection: Mapping[int, Mapping[str, Item]],
    declared_kinds: Mapping[str, Collection],
    severity: str,
    diagnostics: list[Diagnostic],
    line: int | None = None,
) -> None:
    match = TYPED_REFERENCE_PATTERN.match(destination)
    if match is None:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.7",
                f"must be kind:target, found {destination!r}",
                line=line,
            )
        )
        return
    name, target = match.group(1), match.group(2).split("#")[0]
    if not is_registered(name):
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.7",
                f"unknown kind in a typed reference: {name}",
                line=line,
            )
        )
        return
    collection = declared_kinds.get(name)
    if collection is None:
        return  # another source owns this kind; it resolves at sync
    known = by_collection.get(collection.index, {})
    if target not in known:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.7",
                f"unresolved reference: no {name} with the path {target!r} in this repository",
                severity=severity,
                line=line,
            )
        )


def _resolve_relative(source: str, target: str) -> str | None:
    base = PurePosixPath(source).parent
    parts: list[str] = list(base.parts)
    for part in PurePosixPath(target).parts:
        if part == ".":
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _check_asset_file(
    repository: Repository,
    item: Item,
    target: str,
    pointer: str,
    line: int | None,
    diagnostics: list[Diagnostic],
) -> None:
    resolved = _resolve_relative(item.raw.path, target.split("#")[0].split("?")[0])
    if resolved is None:
        diagnostics.append(
            Diagnostic(
                item.raw.path, pointer, "3.6", f"asset leaves the repository: {target}", line=line
            )
        )
        return
    if not resolved.lower().endswith(ASSET_SUFFIXES):
        allowed = ", ".join(suffix.lstrip(".") for suffix in ASSET_SUFFIXES)
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.6",
                f"asset type is not allowed: {resolved}; allowed types are {allowed}",
                line=line,
            )
        )
        return
    source = repository.files.get(resolved)
    if source is None:
        reason = (
            "is ignored by content.yaml" if resolved in repository.ignored else "does not exist"
        )
        diagnostics.append(
            Diagnostic(item.raw.path, pointer, "3.6", f"asset {resolved} {reason}", line=line)
        )
        return
    size = source.stat().st_size
    if size > MAX_ASSET_BYTES:
        diagnostics.append(
            Diagnostic(
                item.raw.path,
                pointer,
                "3.6",
                f"asset {resolved} is {size} bytes, over the {MAX_ASSET_BYTES} byte maximum",
                line=line,
            )
        )


# --- the dialect, section 4.1 ------------------------------------------------


def _check_dialect(item: Item, headings: list[tuple[int, str, str]], diagnostics) -> None:
    title = item.data.get("title")
    for number, line in _code_free_lines(item.body):
        located = item.body_line + number
        for pattern, rule, message, severity in _DIALECT_RULES:
            match = pattern.search(line)
            if match is None:
                continue
            diagnostics.append(
                Diagnostic(
                    item.raw.path,
                    "/body",
                    rule,
                    f"{message}: {match.group(0).strip()[:60]}",
                    severity=severity,
                    line=located,
                )
            )
    for number, line, info in _fenced_blocks(item.body):
        if info != "embed":
            continue
        for message in _check_embed(line):
            diagnostics.append(
                Diagnostic(
                    item.raw.path,
                    "/body",
                    "4.1",
                    message,
                    line=item.body_line + number,
                )
            )
    if headings and isinstance(title, str):
        level, _, text = headings[0]
        if level == 1 and text.strip().lower() == title.strip().lower():
            diagnostics.append(
                Diagnostic(
                    item.raw.path,
                    "/body",
                    "4.1",
                    "the body repeats the title as a leading H1; the renderer strips it",
                    severity=SEVERITY_WARNING,
                    line=item.body_line + 1,
                )
            )


_DIALECT_RULES = (
    (LIQUID_PATTERN, "4.1", "Liquid is not part of the dialect", SEVERITY_ERROR),
    (
        KRAMDOWN_PATTERN,
        "4.1",
        "kramdown attribute lists are not part of the dialect",
        SEVERITY_ERROR,
    ),
    (WIKILINK_PATTERN, "4.1", "[[wikilinks]] are not part of the dialect", SEVERITY_ERROR),
    (IMAGE_TOKEN_PATTERN, "4.1", "{IMAGE:id} tokens are not part of the dialect", SEVERITY_ERROR),
    (RAW_HTML_PATTERN, "4.1", "the sanitiser removes this element", SEVERITY_WARNING),
    (STYLE_ATTRIBUTE_PATTERN, "4.1", "the sanitiser removes style attributes", SEVERITY_WARNING),
    (
        STRIKETHROUGH_PATTERN,
        "4.1",
        "python-markdown has no strikethrough; write <del>",
        SEVERITY_WARNING,
    ),
)


def _check_embed(body: str) -> list[str]:
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as error:
        return [f"an embed fence holds a YAML mapping: {_one_line(error)}"]
    if not isinstance(data, Mapping):
        return ["an embed fence holds a YAML mapping with type and id"]
    problems = []
    if data.get("type") not in ("youtube", "loom"):
        problems.append(f"embed type must be youtube or loom, found {data.get('type')!r}")
    if not data.get("id"):
        problems.append("an embed fence needs an id")
    for key in data:
        if key not in ("type", "id"):
            problems.append(f"unknown embed key: {key}")
    return problems


def _code_free_lines(body: str) -> Iterator[tuple[int, str]]:
    """Body lines outside fenced code, with inline code spans removed."""

    fence: str | None = None
    for number, raw in enumerate(body.split("\n"), start=1):
        match = FENCE_PATTERN.match(raw)
        if fence is not None:
            if match is not None and match.group(2).startswith(fence):
                fence = None
            continue
        if match is not None:
            fence = match.group(2)
            continue
        yield number, INLINE_CODE_PATTERN.sub("", raw)


def _fenced_blocks(body: str) -> Iterator[tuple[int, str, str]]:
    """Every fenced block as (opening line number, content, info string)."""

    fence: str | None = None
    info = ""
    start = 0
    collected: list[str] = []
    for number, raw in enumerate(body.split("\n"), start=1):
        match = FENCE_PATTERN.match(raw)
        if fence is None:
            if match is not None:
                fence = match.group(2)
                info = match.group(3)
                start = number
                collected = []
            continue
        if match is not None and match.group(2).startswith(fence):
            yield start, "\n".join(collected), info
            fence = None
            continue
        collected.append(raw)
    if fence is not None:
        yield start, "\n".join(collected), info


def heading_ids(body: str) -> list[tuple[int, str, str]]:
    """The heading list of a markdown body: `(level, id, text)`.

    The algorithm is the DataTalks.Club one that `FORMAT.md` section 4.1 keeps,
    so a fragment written against a rendered page still checks here. Issue C7.8
    moves the canonical implementation into `content_sync/rendering.py`; this
    copy is the validator's only reason to know it and goes when C7.8 lands.
    """

    seen: dict[str, int] = {}
    headings: list[tuple[int, str, str]] = []
    fence: str | None = None
    for raw in body.split("\n"):
        fence_match = FENCE_PATTERN.match(raw)
        if fence is not None:
            if fence_match is not None and fence_match.group(2).startswith(fence):
                fence = None
            continue
        if fence_match is not None:
            fence = fence_match.group(2)
            continue
        match = HEADING_PATTERN.match(raw)
        if match is None:
            continue
        text = match.group(2).strip()
        base = _heading_slug(text)
        count = seen.get(base, 0)
        seen[base] = count + 1
        headings.append((len(match.group(1)), base if count == 0 else f"{base}-{count}", text))
    return headings


def _heading_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "section"


def _locate(path: str, problem: Problem) -> Diagnostic:
    return Diagnostic(
        path=path,
        pointer=problem.pointer or WHOLE_FILE,
        rule=problem.rule,
        message=problem.message,
        severity=problem.severity,
        line=problem.line,
    )


if __name__ == "__main__":
    sys.exit(main())
