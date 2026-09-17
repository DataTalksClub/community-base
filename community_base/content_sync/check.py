"""`check_content`: a content repository against `FORMAT.md`, with no database.

One implementation, two entry points (specification section 3.10):

    uv run python -m community_base.content_sync.check <path>
    uv run python manage.py check_content <path>

Both call :func:`run_check`, which writes the report and returns the number of
errors. The module entry point turns that into an exit code and the management
command turns it into a `CommandError`; neither owns a rule of its own.

The reading half of the format is not owned here either.
`community_base.content_sync.documents` walks the repository, reads the two
file shapes and checks the manifest, the core and kind keys, naming, slugs,
nesting and identity; a parser reads the same repository through the same code.
This module adds what is left: assets, cross-references and the markdown
dialect of sections 3.6, 3.7 and 4.1.

Every diagnostic carries the repository-relative path of the file, a YAML
pointer into that file (`/` names the file as a whole) and the number of the
rule in `FORMAT.md` it enforces.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from community_base.content_sync.documents import (
    MANIFEST_NAME,
    SCHEMA_VERSION,
    WHOLE_FILE,
    Collection,
    Diagnostic,
    ParsedDocument,
    ReadResult,
    Repository,
    RepositoryManifest,
    locate,
    one_line,
    read_repository,
)
from community_base.content_sync.kinds import ASSET_SUFFIXES, MAX_ASSET_BYTES, is_registered
from community_base.content_sync.kinds.base import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    TYPED_REFERENCE_PATTERN,
    check_asset_reference,
)

__all__ = [
    "MANIFEST_NAME",
    "SCHEMA_VERSION",
    "WHOLE_FILE",
    "Collection",
    "Diagnostic",
    "ParsedDocument",
    "ReadResult",
    "Repository",
    "RepositoryManifest",
    "check_repository",
    "heading_ids",
    "main",
    "read_repository",
    "run_check",
]

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

EXTERNAL_SCHEMES = ("http", "https", "mailto", "tel", "ftp")


def check_repository(path: str | Path, *, kind_modules: Iterable[str] = ()) -> list[Diagnostic]:
    """Every diagnostic for the repository at `path`, sorted by location."""

    result = read_repository(path, kind_modules=kind_modules)
    diagnostics = list(result.diagnostics)
    if result.repository is not None:
        _check_bodies_and_references(result, diagnostics)
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


# --- bodies: assets, references and the dialect ------------------------------


def _check_bodies_and_references(result: ReadResult, diagnostics: list[Diagnostic]) -> None:
    repository = result.repository
    items = result.documents
    severity = SEVERITY_ERROR if result.manifest.strict_references else SEVERITY_WARNING
    by_collection: dict[int, dict[str, ParsedDocument]] = {}
    for item in items:
        by_collection.setdefault(item.collection.index, {})[item.path] = item
    by_document = result.by_path()
    declared_kinds = {
        collection.kind.name: collection for collection in result.manifest.collections
    }
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


def _check_asset_keys(
    repository: Repository, item: ParsedDocument, diagnostics: list[Diagnostic]
) -> None:
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


def _references(item: ParsedDocument) -> Iterator[Reference]:
    for number, line in _code_free_lines(item.body):
        for match in LINK_PATTERN.finditer(line):
            yield Reference(match.group(3), item.body_line + number, match.group(1) == "!")
        for match in HTML_IMG_PATTERN.finditer(line):
            yield Reference(match.group(1), item.body_line + number, True)


def _reference_key_values(item: ParsedDocument) -> Iterator[tuple[str, str]]:
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
    item: ParsedDocument,
    reference: Reference,
    by_collection: Mapping[int, Mapping[str, ParsedDocument]],
    by_document: Mapping[str, ParsedDocument],
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
                diagnostics.append(locate(item.raw.path, problem))
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
            diagnostics.append(locate(item.raw.path, problem))
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
    item: ParsedDocument,
    destination: str,
    pointer: str,
    by_collection: Mapping[int, Mapping[str, ParsedDocument]],
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
    item: ParsedDocument,
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
    if resolved not in repository.files:
        reason = (
            "is ignored by content.yaml" if resolved in repository.ignored else "does not exist"
        )
        diagnostics.append(
            Diagnostic(item.raw.path, pointer, "3.6", f"asset {resolved} {reason}", line=line)
        )
        return
    size = repository.size(resolved)
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


def _check_dialect(item: ParsedDocument, headings: list[tuple[int, str, str]], diagnostics) -> None:
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
        return [f"an embed fence holds a YAML mapping: {one_line(error)}"]
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


if __name__ == "__main__":
    sys.exit(main())
