"""The document toolkit: a checkout plus `content.yaml` into parsed records.

This module is the reading half of the content format (`FORMAT.md` sections 3.1
to 3.5): the repository manifest, the collection walk, the two file shapes, the
core and kind keys, slug and `sort_order` derivation, the nesting rules, the
identity rules and the derived-record checksum. It renders nothing and uploads
nothing; assets and cross-references are issue C7.9b.

There is one implementation of those rules, not two. `check.py` is a consumer:
:func:`read_repository` produces the diagnostics for every rule in this half and
the validator adds the body, asset, reference and dialect checks on top. A
parser is the other consumer and reads :class:`ParsedDocument` values rather
than walking files, parsing YAML or validating keys again.

Errors are bounded and named: nothing here raises on a malformed repository.
Every violation becomes one :class:`Diagnostic` carrying the repository-relative
path of the file, a YAML pointer into it and the number of the rule in
`FORMAT.md`, and the walk continues, so one pass reports every violation a
collection has rather than the first.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from community_base.content_sync.kinds import (
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
    split_order_prefix,
)
from community_base.content_sync.kinds.base import (
    DATA_SUFFIXES,
    DATE_PREFIX_PATTERN,
    SEVERITY_ERROR,
    SHAPE_DATA,
    SLUG_PATTERN,
    applied_defaults,
    resolve_level,
)

MANIFEST_NAME = "content.yaml"
SCHEMA_VERSION = 1
WHOLE_FILE = "/"

MANIFEST_KEYS = ("schema_version", "collections", "ignore", "strict_references", "theme_pairs")
COLLECTION_KEYS = ("kind", "path")
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
    """One `collections` entry of `content.yaml`, after validation."""

    kind: KindSpec
    path: str
    index: int

    @property
    def pointer(self) -> str:
        return f"/collections/{self.index}"


@dataclass(frozen=True, slots=True)
class RepositoryManifest:
    """`content.yaml` (section 3.1), with its defaults applied."""

    data: Mapping[str, Any] = field(default_factory=dict)
    collections: tuple[Collection, ...] = ()
    ignore: tuple[str, ...] = ()
    strict_references: bool = True
    theme_pairs: bool = False


@dataclass(slots=True)
class ParsedDocument:
    """One item of one collection, read and derived once.

    `collection`, `part` and `raw` say where the item came from and which
    schema it was read against. `content` is the file as it parsed, `values`
    the same mapping with the registry's defaults filled in, and `body` the
    markdown after the front matter, unrendered. `slug`, `sort_order`, `path`
    and `required_level` are derived by sections 3.3 and 3.4. `checksum`
    covers the whole derived record, so moving a file without editing it
    changes it.
    """

    collection: Collection
    part: PartSpec
    raw: RawItem
    content: Any
    data: dict[str, Any]
    values: dict[str, Any]
    body: str
    body_line: int
    slug: str
    sort_order: int
    required_level: int
    path: str
    is_document: bool
    checksum: str = ""

    @property
    def kind(self) -> str:
        return self.collection.kind.name

    @property
    def source_path(self) -> str:
        """The repository-relative path of the file this item was read from."""

        return self.raw.path

    @property
    def content_id(self) -> str | None:
        value = self.data.get("content_id")
        return value if isinstance(value, str) else None

    @property
    def title(self) -> str:
        value = self.values.get("title")
        return value if isinstance(value, str) else ""

    @property
    def sort_key(self) -> tuple[int, str]:
        """Sibling order (section 3.3): `sort_order`, ties broken by slug."""

        return (self.sort_order, self.slug)

    @property
    def key(self) -> str:
        """What names this item inside its repository: its kind and its path."""

        return f"{self.kind}:{self.path}"

    def record(self) -> dict[str, Any]:
        """The derived record the checksum covers.

        Everything a consumer stores is in here: where the file sits, what the
        item derived from its name and its ancestors, what the file declared
        and what the registry defaulted.
        """

        return {
            "kind": self.kind,
            "part": self.part.name,
            "source_path": self.raw.path,
            "parent": self.raw.parent,
            "path": self.path,
            "slug": self.slug,
            "sort_order": self.sort_order,
            "required_level": self.required_level,
            "content": self.content,
            "values": self.values,
            "body": self.body,
        }


@dataclass(slots=True)
class Repository:
    """Everything read from disk once, so every check works on the same view.

    `root` is a real directory: an immutable checkout materialises one, and the
    walk uses it for names alone. File contents go through :meth:`read_text`,
    which reads through the checkout when there is one, so the checkout's
    manifest hash still guards every byte the toolkit parses.
    """

    root: Path
    tree: DirNode
    files: dict[str, Path] = field(default_factory=dict)
    ignored: set[str] = field(default_factory=set)
    checkout: Any = None

    def read_text(self, rel: str) -> str:
        if self.checkout is not None:
            return self.checkout.read_text(rel)
        return self.files[rel].read_text(encoding="utf-8")

    def read_bytes(self, rel: str) -> bytes:
        """The bytes of one file, through the checkout when there is one.

        An asset is checked and uploaded by its bytes (section 3.6), so this is
        the same guarded read the text side uses and not a second path to disk.
        """

        if self.checkout is not None:
            return self.checkout.read_bytes(rel)
        return self.files[rel].read_bytes()

    def size(self, rel: str) -> int:
        return self.files[rel].stat().st_size


@dataclass(frozen=True, slots=True)
class ReadResult:
    """What one repository yielded: its manifest, its documents, its problems."""

    root: Path
    manifest: RepositoryManifest = field(default_factory=RepositoryManifest)
    documents: tuple[ParsedDocument, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    repository: Repository | None = None

    @property
    def collections(self) -> tuple[Collection, ...]:
        return self.manifest.collections

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == SEVERITY_ERROR)

    @property
    def ok(self) -> bool:
        """True when no rule of the reading half rejected this repository."""

        return not self.errors

    def by_kind(self, name: str) -> tuple[ParsedDocument, ...]:
        return tuple(item for item in self.documents if item.kind == name)

    def by_part(self, name: str) -> tuple[ParsedDocument, ...]:
        return tuple(item for item in self.documents if item.part.name == name)

    def by_path(self) -> dict[str, ParsedDocument]:
        """Every document by the repository path of the file it was read from."""

        return {item.raw.path: item for item in self.documents}


def read_repository(source: Any, *, kind_modules: Iterable[str] = ()) -> ReadResult:
    """Read one content repository into :class:`ParsedDocument` values.

    `source` is a path to a directory or an
    :class:`~community_base.content_sync.checkout.ImmutableCheckout`. Nothing
    raises: a repository the toolkit cannot read comes back as diagnostics.
    """

    for module in kind_modules:
        importlib.import_module(module)
    checkout = None if isinstance(source, str | Path) else source
    root = Path(source if checkout is None else checkout.root)
    if not root.is_dir():
        return ReadResult(
            root=root,
            diagnostics=(Diagnostic(str(source), WHOLE_FILE, "3.1", "is not a directory"),),
        )
    if not (root / MANIFEST_NAME).is_file():
        return ReadResult(
            root=root,
            diagnostics=(
                Diagnostic(
                    MANIFEST_NAME, WHOLE_FILE, "3.1", "every synced repository needs this file"
                ),
            ),
        )
    text = (
        checkout.read_text(MANIFEST_NAME)
        if checkout is not None
        else (root / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    data, problems = _parse_yaml(text)
    if problems:
        return ReadResult(
            root=root,
            diagnostics=tuple(locate(MANIFEST_NAME, problem) for problem in problems),
        )
    diagnostics: list[Diagnostic] = []
    manifest = _read_manifest(data, diagnostics)
    repository = _read_repository(root, manifest.ignore, checkout)
    documents: list[ParsedDocument] = []
    for collection in manifest.collections:
        documents.extend(_read_collection(repository, collection, diagnostics))
    _check_identity(documents, diagnostics)
    return ReadResult(
        root=root,
        manifest=manifest,
        documents=tuple(documents),
        diagnostics=tuple(sorted(diagnostics, key=lambda item: item.sort_key)),
        repository=repository,
    )


# --- the repository manifest, section 3.1 ------------------------------------


def _read_manifest(data: Any, diagnostics: list[Diagnostic]) -> RepositoryManifest:
    if not isinstance(data, Mapping):
        diagnostics.append(
            Diagnostic(MANIFEST_NAME, WHOLE_FILE, "3.1", "top level must be a mapping")
        )
        return RepositoryManifest()
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
    flags = {"strict_references": True, "theme_pairs": False}
    for key in flags:
        if key not in data:
            continue
        if isinstance(data[key], bool):
            flags[key] = data[key]
        else:
            diagnostics.append(Diagnostic(MANIFEST_NAME, f"/{key}", "3.1", "must be true or false"))
    ignore: tuple[str, ...] = ()
    if "ignore" in data:
        if _is_string_list(data["ignore"]):
            ignore = tuple(data["ignore"])
        else:
            diagnostics.append(
                Diagnostic(MANIFEST_NAME, "/ignore", "3.1", "must be a list of globs")
            )
    return RepositoryManifest(
        data=data,
        collections=_read_collections(data, diagnostics),
        ignore=ignore,
        strict_references=flags["strict_references"],
        theme_pairs=flags["theme_pairs"],
    )


def _read_collections(
    data: Mapping[str, Any], diagnostics: list[Diagnostic]
) -> tuple[Collection, ...]:
    declared = data.get("collections")
    if not isinstance(declared, list) or not declared:
        diagnostics.append(
            Diagnostic(MANIFEST_NAME, "/collections", "3.1", "must list at least one collection")
        )
        return ()
    collections: list[Collection] = []
    for index, entry in enumerate(declared):
        collection = _read_collection_entry(entry, index, diagnostics)
        if collection is not None:
            collections.append(collection)
    _check_collection_paths(collections, diagnostics)
    return tuple(collections)


def _read_collection_entry(
    entry: Any, index: int, diagnostics: list[Diagnostic]
) -> Collection | None:
    pointer = f"/collections/{index}"
    if not isinstance(entry, Mapping):
        diagnostics.append(Diagnostic(MANIFEST_NAME, pointer, "3.1", "must be a mapping"))
        return None
    for key in entry:
        if key not in COLLECTION_KEYS:
            diagnostics.append(
                Diagnostic(MANIFEST_NAME, f"{pointer}/{key}", "3.1", f"unknown key: {key}")
            )
    name = entry.get("kind")
    path = entry.get("path")
    if not isinstance(name, str) or not name:
        diagnostics.append(Diagnostic(MANIFEST_NAME, f"{pointer}/kind", "3.1", "must name a kind"))
        return None
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
        return None
    if not isinstance(path, str) or not path:
        diagnostics.append(
            Diagnostic(
                MANIFEST_NAME, f"{pointer}/path", "3.1", "must be a repository-relative directory"
            )
        )
        return None
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
        return None
    return Collection(kind=get_kind(name), path=normalised, index=index)


def _check_collection_paths(collections: list[Collection], diagnostics: list[Diagnostic]) -> None:
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


def _normalise_collection_path(path: str) -> str | None:
    candidate = PurePosixPath(path.strip())
    if str(candidate) in (".", ""):
        return ""
    parts = [part for part in candidate.parts if part != "."]
    if any(part == ".." for part in parts) or candidate.is_absolute():
        return None
    return "/".join(parts)


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


# --- reading the repository --------------------------------------------------


def _read_repository(root: Path, patterns: tuple[str, ...], checkout: Any = None) -> Repository:
    repository = Repository(root=root, tree=DirNode(path=""), checkout=checkout)
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


def _read_collection(
    repository: Repository, collection: Collection, diagnostics: list[Diagnostic]
) -> list[ParsedDocument]:
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
        diagnostics.append(locate(path, problem))
    documents: list[ParsedDocument] = []
    by_path: dict[str, ParsedDocument] = {}
    for raw in raw_items:
        document = _read_item(repository, collection, raw, diagnostics)
        if document is None:
            continue
        documents.append(document)
        by_path[raw.path] = document
    for document in documents:
        document.path = _derive_path(document, by_path)
        document.required_level = _derive_level(document, by_path)
        document.checksum = _checksum(document)
    _check_siblings(documents, diagnostics)
    return documents


def _read_item(
    repository: Repository,
    collection: Collection,
    raw: RawItem,
    diagnostics: list[Diagnostic],
) -> ParsedDocument | None:
    part = collection.kind.part(raw.part)
    if raw.path not in repository.files:  # pragma: no cover -- the tree named it a moment ago
        return None
    if _is_document(raw.path):
        content, body, body_line, problems = _load_document(repository, raw.path)
    else:
        content, problems = _load_yaml(
            repository, raw.path, require_mapping=part.shape != SHAPE_DATA
        )
        body, body_line = "", 0
    for problem in problems:
        diagnostics.append(locate(raw.path, problem))
    if problems:
        return None
    if isinstance(content, Mapping):
        data = dict(content)
        for problem in check_item_keys(content, part):
            diagnostics.append(locate(raw.path, problem))
    elif part.shape != SHAPE_DATA:  # pragma: no cover -- _load_yaml refuses it
        return None
    else:
        # Section 3.8: a `data` file is opaque, and a top-level list is as
        # acceptable as a mapping. It carries no keys, so nothing derives from
        # one; the parsed value rides on `content` untouched.
        data = {}
    diagnostics.extend(_check_name(raw))
    slug = _item_slug(collection, raw, data, diagnostics)
    if slug is None:
        return None
    return ParsedDocument(
        collection=collection,
        part=part,
        raw=raw,
        content=content,
        data=data,
        values=applied_defaults(data, part),
        body=body,
        body_line=body_line,
        slug=slug,
        sort_order=_item_sort_order(raw, data),
        required_level=0,
        path=slug,
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


def _item_sort_order(raw: RawItem, data: Mapping[str, Any]) -> int:
    """Section 3.4: the `NN-` prefix of the name, unless front matter overrides."""

    declared = data.get("sort_order")
    if isinstance(declared, int) and not isinstance(declared, bool):
        return declared
    prefix, _ = split_order_prefix(raw.name)
    return prefix or 0


def _derive_path(document: ParsedDocument, by_path: Mapping[str, ParsedDocument]) -> str:
    """Section 3.4: the chain of ancestor slugs, relative to the collection root.

    The `data` kind is keyed by its path below the collection root without the
    extension instead (section 3.8), so `graph/graph.json` and
    `search/search-corpus.json` keep distinct keys in one collection where a
    file stem could not.
    """

    if document.collection.kind.shape == SHAPE_DATA:
        return _data_key(document)
    parts: list[str] = []
    current: ParsedDocument | None = document
    seen: set[str] = set()
    while current is not None and current.raw.path not in seen:
        seen.add(current.raw.path)
        if current.raw.contributes_slug:
            parts.append(current.slug)
        parent = current.raw.parent
        current = by_path.get(parent) if parent else None
    return "/".join(reversed(parts))


def _data_key(document: ParsedDocument) -> str:
    root = document.collection.path
    relative = document.raw.path
    if root and relative.startswith(f"{root}/"):
        relative = relative[len(root) + 1 :]
    for suffix in DATA_SUFFIXES:
        if relative.endswith(suffix):
            return relative[: -len(suffix)]
    return relative  # pragma: no cover -- DataLayout yields those suffixes only


def _derive_level(document: ParsedDocument, by_path: Mapping[str, ParsedDocument]) -> int:
    """Section 3.3: `required_level`, inherited from the parent item, else 0."""

    current: ParsedDocument | None = document
    seen: set[str] = set()
    while current is not None and current.raw.path not in seen:
        seen.add(current.raw.path)
        declared = resolve_level(current.data.get("required_level"))
        if declared is not None:
            return declared
        parent = current.raw.parent
        current = by_path.get(parent) if parent else None
    return 0


def _checksum(document: ParsedDocument) -> str:
    """A digest of the whole derived record, not of the file bytes.

    Two files with the same bytes in different places are different records:
    their repository path, their derived path and their sibling order differ,
    and a consumer that keys on this checksum has to see that.
    """

    payload = json.dumps(document.record(), sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_siblings(documents: list[ParsedDocument], diagnostics: list[Diagnostic]) -> None:
    seen: dict[tuple[str, str, str], ParsedDocument] = {}
    for document in documents:
        key = (document.raw.part, document.raw.container, document.slug)
        first = seen.get(key)
        if first is not None:
            diagnostics.append(
                Diagnostic(
                    document.raw.path,
                    "/slug",
                    "3.4",
                    f"two siblings resolve to the slug {document.slug!r};"
                    f" {first.raw.path} has it too",
                )
            )
            continue
        seen[key] = document


def _check_identity(documents: list[ParsedDocument], diagnostics: list[Diagnostic]) -> None:
    """Section 3.4: `content_id` is unique across the repository, any kind."""

    seen: dict[str, ParsedDocument] = {}
    for document in documents:
        content_id = document.content_id
        if content_id is None:
            continue
        first = seen.get(content_id)
        if first is not None:
            diagnostics.append(
                Diagnostic(
                    document.raw.path,
                    "/content_id",
                    "3.4",
                    f"content_id {content_id} is already used by {first.raw.path}",
                )
            )
            continue
        seen[content_id] = document


# --- file shapes, section 3.2 ------------------------------------------------


def _parse_yaml(text: str, *, require_mapping: bool = True) -> tuple[Any, list[Problem]]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return None, [Problem(WHOLE_FILE, "3.2", f"is not valid YAML: {one_line(error)}")]
    if data is None:
        return None, [Problem(WHOLE_FILE, "3.2", "is empty")]
    if require_mapping and not isinstance(data, Mapping):
        return None, [Problem(WHOLE_FILE, "3.2", "top level must be a mapping")]
    return data, []


def _load_yaml(
    repository: Repository, rel: str, *, require_mapping: bool = True
) -> tuple[Any, list[Problem]]:
    try:
        text = repository.read_text(rel)
    except UnicodeDecodeError:
        return None, [Problem(WHOLE_FILE, "3.2", "must be UTF-8")]
    return _parse_yaml(text, require_mapping=require_mapping)


def _load_document(repository: Repository, rel: str) -> tuple[Any, str, int, list[Problem]]:
    try:
        text = repository.read_text(rel)
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
            [Problem(WHOLE_FILE, "3.2", f"front matter is not valid YAML: {one_line(error)}")],
        )
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        return None, "", 0, [Problem(WHOLE_FILE, "3.2", "front matter must be a mapping")]
    body = "\n".join(lines[closing + 1 :])
    return data, body, closing + 1, []


def one_line(error: Exception) -> str:
    """An exception message on one line, for a diagnostic."""

    return " ".join(str(error).split())


def _is_document(path: str) -> bool:
    """Section 3.2: a `.md` file is a document, everything else a manifest."""

    return path.endswith(".md")


def locate(path: str, problem: Problem) -> Diagnostic:
    """A :class:`Problem` a schema raised, plus the file it is about."""

    return Diagnostic(
        path=path,
        pointer=problem.pointer or WHOLE_FILE,
        rule=problem.rule,
        message=problem.message,
        severity=problem.severity,
        line=problem.line,
    )
