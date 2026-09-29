"""Resolve cohort bindings to either legacy manifests or authored course units."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping
from typing import Any

from community_base.content_sync.documents import Collection, ParsedDocument, ReadResult
from community_base.coursework.manifests import (
    DEFAULT_INSTRUCTIONS,
    HOMEWORK_PART,
    HOMEWORK_UNIT_KIND,
    RULE,
    HomeworkGraph,
    HomeworkManifestError,
    _due_at,
    _form,
    _questions,
)
from community_base.curriculum.source import CohortGraph, ModuleGraph, ParsedCurriculum, UnitGraph


def read_cohort_homework(
    result: ReadResult, collection: Collection, parsed: ParsedCurriculum
) -> tuple[HomeworkGraph, ...]:
    """Every manifest the course's cohorts bind, in cohort then binding order."""

    manifests, source_units = _documents(result, collection)
    from community_base.coursework.course_tree import validate_source_unit

    source_questions = {}
    for identity, document in source_units.items():
        source_questions[identity] = validate_source_unit(document)
    course = parsed.course
    units = {}
    for unit in _units(course.modules):
        if unit.content_id:
            units[unit.content_id] = unit
    found: list[HomeworkGraph] = []
    for cohort in course.cohorts:
        found.extend(
            _cohort_homework(
                result, cohort, course, manifests, source_units, source_questions, units
            )
        )
    return tuple(found)


def _documents(result, collection):
    manifests = {}
    source_units = {}
    for document in result.documents:
        if document.collection.index != collection.index:
            continue
        if document.part.name == HOMEWORK_PART:
            manifests[document.raw.path] = document
        if document.part.name == "homework_unit":
            source_units[document.content_id] = document
    return manifests, source_units


def _cohort_homework(result, cohort, course, manifests, source_units, source_questions, units):
    placed = _placed_module_slugs(cohort, course.modules)
    bound_slugs = set()
    found = []
    for index, binding in enumerate(cohort.homework_bindings):
        graph = _binding_graph(
            result,
            cohort,
            binding,
            index,
            manifests,
            source_units,
            source_questions,
            placed,
            units,
            course,
        )
        if graph.slug in bound_slugs:
            where = cohort.source_path or cohort.slug
            raise HomeworkManifestError(
                f"{where}:/homework/{index}: [{RULE}] duplicate assignment slug {graph.slug!r}"
            )
        bound_slugs.add(graph.slug)
        found.append(graph)
    return found


def _binding_graph(
    result, cohort, binding, index, manifests, sources, questions, placed, units, course
):
    if not binding.get("source"):
        from community_base.coursework.course_tree import read_course_tree_binding

        return read_course_tree_binding(
            result, cohort, binding, index, sources, placed, units, course.modules, questions
        )
    return _homework_graph(
        result,
        cohort,
        binding,
        index,
        manifests=manifests,
        placed=placed,
        units=units,
        course_slug=course.slug,
    )


def _units(modules: Iterable[ModuleGraph]) -> Iterable[UnitGraph]:
    for module in modules:
        yield from module.units
        yield from _units(module.children)


def _placed_module_slugs(cohort: CohortGraph, modules: tuple[ModuleGraph, ...]) -> set[str]:
    """The top-level module slugs this cohort places (section 3.8, `modules`)."""

    if cohort.module_refs is None:
        return {module.slug for module in modules}
    by_ref = {module.content_id or module.slug: module.slug for module in modules}
    placed = set()
    for ref in cohort.module_refs:
        if ref in by_ref:
            placed.add(by_ref[ref])
    return placed


def _homework_graph(
    result: ReadResult,
    cohort: CohortGraph,
    binding: Mapping[str, Any],
    index: int,
    *,
    manifests: Mapping[str, ParsedDocument],
    placed: set[str],
    units: Mapping[str, UnitGraph],
    course_slug: str,
) -> HomeworkGraph:
    where = cohort.source_path or cohort.slug
    pointer = f"/homework/{index}"
    module_slug = binding.get("module")
    if module_slug not in placed:
        raise HomeworkManifestError(
            f"{where}:{pointer}/module: [{RULE}] the cohort does not place the module "
            f"{module_slug!r}; a binding assigns homework to a module the cohort places"
        )
    path = _manifest_path(where, pointer, cohort, binding.get("source"))
    document = manifests.get(path)
    if document is None:
        raise HomeworkManifestError(
            f"{where}:{pointer}/source: [{RULE}] no homework manifest at {path!r}; "
            "a binding names homework/<module-slug>/homework.yaml under its cohort"
        )
    unit_content_id = _unit_content_id(where, pointer, binding.get("unit"), units)
    return _legacy_graph(result, document, cohort, module_slug, unit_content_id, course_slug)


def _legacy_graph(result, document, cohort, module_slug, unit_content_id, course_slug):
    values = document.values
    instructions_path, instructions = _instructions(result, document)
    return HomeworkGraph(
        content_id=document.content_id,
        slug=document.slug,
        title=document.title,
        source_path=document.raw.path,
        cohort_slug=cohort.slug,
        module_slug=module_slug,
        unit_content_id=unit_content_id,
        instructions_source_path=instructions_path,
        instructions_markdown=instructions,
        due_at=_due_at(values.get("due_at")),
        initial_state=values.get("initial_state") or "closed",
        form=_form(values.get("form") or {}),
        questions=_questions(document, course_slug=course_slug),
    )


def _manifest_path(where: str, pointer: str, cohort: CohortGraph, source: Any) -> str:
    """The binding's `source`, resolved against the cohort directory.

    Section 3.8 makes everything below the cohort directory the cohort's own,
    so a source that climbs out of it is refused rather than resolved.
    """

    directory = posixpath.dirname(cohort.source_path or "")
    candidate = posixpath.normpath(posixpath.join(directory, str(source or "")))
    if candidate.startswith("..") or not candidate.startswith(f"{directory}/"):
        raise HomeworkManifestError(
            f"{where}:{pointer}/source: [{RULE}] {source!r} is outside the cohort directory"
        )
    return candidate


def _unit_content_id(
    where: str, pointer: str, value: Any, units: Mapping[str, UnitGraph]
) -> str | None:
    """A binding's optional `unit`: the page that shows the submission form."""

    if not value:
        return None
    unit = units.get(str(value))
    if unit is None:
        raise HomeworkManifestError(
            f"{where}:{pointer}/unit: [{RULE}] no unit of this course carries the "
            f"content_id {value!r}"
        )
    if unit.kind != HOMEWORK_UNIT_KIND:
        raise HomeworkManifestError(
            f"{where}:{pointer}/unit: [{RULE}] {unit.source_path} is a {unit.kind} unit; "
            "a binding's unit is the kind: homework unit whose page shows the form"
        )
    return unit.content_id


def _instructions(result: ReadResult, document: ParsedDocument) -> tuple[str, str]:
    """The manifest's instructions file, beside it in the same directory."""

    name = document.values.get("instructions_path") or DEFAULT_INSTRUCTIONS
    directory = posixpath.dirname(document.raw.path)
    path = posixpath.normpath(posixpath.join(directory, name))
    repository = result.repository
    if not path.startswith(f"{directory}/"):
        raise HomeworkManifestError(
            f"{document.raw.path}:/instructions_path: [{RULE}] {name!r} is outside the "
            "homework directory"
        )
    if repository is None or path not in repository.files:
        raise HomeworkManifestError(
            f"{document.raw.path}:/instructions_path: [{RULE}] no file at {path!r}"
        )
    return path, repository.read_text(path)
