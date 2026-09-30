"""Validate only newly supported course shapes on a proposed converted tree."""

from __future__ import annotations

import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from community_base.content_sync.documents import read_repository
from community_base.coursework.course_tree import validate_source_unit
from community_base.coursework.manifests import HomeworkManifestError, read_cohort_homework
from community_base.curriculum.parsers import parse_course
from community_base.curriculum.source import CurriculumParseError
from community_base.curriculum.source_tree import module_graphs

Failure = tuple[str, str, str, str]


def mixed_directories(root: Path, modules: set[str], ignored: Callable[[str], bool]) -> set[str]:
    """Parents containing both direct units and child modules or homework."""

    found = set()
    for rel in modules:
        if ignored(f"{rel}/module.yaml"):
            continue
        has_unit = has_module = False
        for item in (root / rel).iterdir():
            path = item.relative_to(root).as_posix()
            if ignored(path):
                continue
            if item.is_file() and item.suffix == ".md" and item.name != "README.md":
                has_unit = True
            if item.is_dir():
                if (item / "homework.yaml").is_file() and not ignored(f"{path}/homework.yaml"):
                    has_unit = True
                if (item / "module.yaml").is_file() and not ignored(f"{path}/module.yaml"):
                    has_module = True
        if has_unit and has_module:
            found.add(rel)
    return found


def validate_proposed(
    root: Path,
    writes: list[tuple[str, str]],
    mixed: set[str],
    bindings: set[str],
    homework_units: set[str],
) -> list[Failure]:
    """Ask the shared graph readers about a disposable proposed output."""

    if not mixed and not bindings and not homework_units:
        return []
    with tempfile.TemporaryDirectory(prefix="cb-course-preview-") as temporary:
        proposed = Path(temporary) / "tree"
        shutil.copytree(root, proposed, ignore=shutil.ignore_patterns(".git"))
        for path, text in writes:
            target = proposed / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return _inspect(proposed, mixed, bindings, homework_units)


def _inspect(
    root: Path, mixed: set[str], bindings: set[str], homework_units: set[str]
) -> list[Failure]:
    result = read_repository(root)
    failures = _read_failures(result, mixed, bindings, homework_units)
    failures.extend(_source_failures(result, mixed, bindings, homework_units))
    failures.extend(_mixed_failures(result, mixed))
    if failures:
        return [*failures, *_unavailable_bindings(bindings, "source validation failed")]
    if not bindings:
        return []
    if result.errors:
        return _unavailable_bindings(bindings, result.errors[0].render())
    return _binding_failures(result, mixed, bindings, homework_units)


def _read_failures(result, mixed, bindings, homework_units) -> list[Failure]:
    failures = []
    for diagnostic in result.errors:
        scope = _scope(diagnostic.path, mixed, bindings, homework_units)
        if scope:
            failures.append((diagnostic.path, diagnostic.rule, diagnostic.render(), scope))
    return failures


def _source_failures(result, mixed, bindings, homework_units) -> list[Failure]:
    failures = []
    for document in result.documents:
        if document.part.name != "homework_unit" or document.raw.path not in homework_units:
            continue
        try:
            validate_source_unit(document)
        except HomeworkManifestError as error:
            failure = _graph_failure(str(error), mixed, bindings, homework_units)
            if failure:
                failures.append(failure)
    return failures


def _binding_failures(result, mixed, bindings, homework_units) -> list[Failure]:
    collection = _course_collection(result)
    if collection is None:
        return _unavailable_bindings(bindings, "no course collection")
    failures = []
    for path in sorted(bindings):
        scoped = _one_cohort(result, path)
        try:
            parsed = parse_course(scoped, collection)
            read_cohort_homework(scoped, collection, parsed)
        except (CurriculumParseError, HomeworkManifestError) as error:
            failure = _graph_failure(str(error), mixed, {path}, homework_units)
            if failure:
                failures.append(failure)
            else:
                failures.extend(_unavailable_bindings({path}, str(error)))
    return failures


def _one_cohort(result, path):
    documents = []
    for document in result.documents:
        if document.part.name != "cohort" or document.raw.path == path:
            documents.append(document)
    return replace(result, documents=tuple(documents))


def _unavailable_bindings(bindings: set[str], reason: str) -> list[Failure]:
    failures = []
    for path in sorted(bindings):
        failures.append((path, "3.8", f"binding cannot be validated: {reason}", path))
    return failures


def _course_collection(result):
    for collection in result.collections:
        if collection.kind.name == "course":
            return collection
    return None


def _mixed_failures(result, mixed: set[str]) -> list[Failure]:
    parents = defaultdict(list)
    for document in result.documents:
        parents[document.raw.parent].append(document)
    by_path = result.by_path()
    failures = []
    for rel in sorted(mixed):
        module = by_path.get(f"{rel}/module.yaml")
        if module is None:
            continue
        siblings = parents.get(module.raw.path, [])
        scoped = {"__preview__": [module], module.raw.path: siblings}
        for child in siblings:
            if child.part.name == "module":
                scoped[child.raw.path] = []
        try:
            module_graphs(result, scoped, parent="__preview__", inherited=None)
        except CurriculumParseError as error:
            path = str(error).split(":", 1)[0]
            failures.append((path, "3.8", str(error), rel))
    return failures


def _scope(path: str, mixed: set[str], bindings: set[str], homework_units: set[str]) -> str:
    if path in bindings:
        return path
    for manifest in homework_units:
        directory = manifest.rsplit("/", 1)[0]
        if path == manifest or path.startswith(f"{directory}/"):
            return directory
    for directory in sorted(mixed, key=len, reverse=True):
        if path.startswith(f"{directory}/"):
            return directory
    return ""


def _graph_failure(
    message: str, mixed: set[str], bindings: set[str], homework_units: set[str]
) -> Failure | None:
    path = message.split(":", 1)[0]
    scope = _scope(path, mixed, bindings, homework_units)
    if not scope:
        return None
    return path, "3.8", message, scope
