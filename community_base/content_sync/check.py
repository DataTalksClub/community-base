"""`check_content`: a content repository against `FORMAT.md`, with no database.

One implementation, two entry points (specification section 3.10):

    uv run python -m community_base.content_sync.check <path>
    uv run python manage.py check_content <path>

Both call :func:`run_check`, which writes the report and returns the number of
errors. The module entry point turns that into an exit code and the management
command turns it into a `CommandError`; neither owns a rule of its own.

No rule of the format is owned here.
`community_base.content_sync.documents` walks the repository, reads the two
file shapes and checks the manifest, the core and kind keys, naming, slugs,
nesting and identity; `community_base.content_sync.resolution` resolves the
assets and the cross-references of sections 3.6 and 3.7 and reports what does
not resolve. A parser reads the same repository through the same two modules.
What is left here, and only here, is the markdown dialect of section 4.1: the
rules that reject a construct rather than resolve one.

The validator differs from a sync in the two arguments it does not pass: no
media store, so nothing is uploaded, and no route resolver, so a reference to a
kind another source owns is left for the sync that has that source.

Every diagnostic carries the repository-relative path of the file, a YAML
pointer into that file (`/` names the file as a whole) and the number of the
rule in `FORMAT.md` it enforces.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

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
    one_line,
    read_repository,
)
from community_base.content_sync.kinds.base import SEVERITY_ERROR, SEVERITY_WARNING
from community_base.content_sync.rendering import HeadingIdAssigner
from community_base.content_sync.resolution import resolve_repository

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
LIQUID_PATTERN = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")
KRAMDOWN_PATTERN = re.compile(r"\{:\s*[.#][^}]*\}")
WIKILINK_PATTERN = re.compile(r"\[\[[^\]]+\]\]")
IMAGE_TOKEN_PATTERN = re.compile(r"\{IMAGE:[^}]*\}")
STRIKETHROUGH_PATTERN = re.compile(r"~~[^~\s][^~]*~~")
RAW_HTML_PATTERN = re.compile(r"<\s*(script|style|iframe)\b", re.IGNORECASE)
STYLE_ATTRIBUTE_PATTERN = re.compile(r"<[^>]*\sstyle\s*=", re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def check_repository(path: str | Path, *, kind_modules: Iterable[str] = ()) -> list[Diagnostic]:
    """Every diagnostic for the repository at `path`, sorted by location."""

    result = read_repository(path, kind_modules=kind_modules)
    diagnostics = [*result.diagnostics, *resolve_repository(result).diagnostics]
    for item in result.documents:
        if item.is_document:
            _check_dialect(item, heading_ids(item.body), diagnostics)
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

    The ids come from `rendering.HeadingIdAssigner`, the one implementation of
    the DataTalks.Club algorithm `FORMAT.md` section 4.1 keeps, so the fragment
    this validator accepts is the fragment the rendered page carries. Only the
    walk over markdown source is the validator's own: it checks a repository
    before anything renders it.
    """

    assigner = HeadingIdAssigner()
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
        headings.append((len(match.group(1)), assigner.assign(text), text))
    return headings


if __name__ == "__main__":
    sys.exit(main())
