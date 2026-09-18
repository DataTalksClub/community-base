"""The one course parser: `FORMAT.md` section 3.8 onto the curriculum graph.

This module maps and nothing else. The document toolkit
(:mod:`community_base.content_sync.documents`) owns the collection walk, the
two file shapes, the core and kind keys, slug and `sort_order` derivation,
`required_level` inheritance, identity and checksums; the kind registry
(:mod:`community_base.content_sync.kinds`) owns the course layout and the
per-part schemas. Nothing here opens a directory, parses YAML or decides
whether a key is allowed: a violation of any of those rules is already a
:class:`~community_base.content_sync.documents.Diagnostic` when this module
runs, and the parser reports it with the file, the pointer and the rule number
the toolkit gave it.

What is left, and what this module is, is the mapping: which
:class:`~community_base.content_sync.documents.ParsedDocument` is the course,
which are its modules and units, which cohort places which module, and what
each of them becomes in :mod:`community_base.curriculum.source`.

Package rulings, written here because section 3.8 is silent about them.

- A course that declares no `cohorts/` directory gets one implicit open-ended
  self-paced cohort placing the full tree. The shared model delivers a course
  through a cohort, and `curriculum.services.get_or_create_self_paced_cohort`
  already mints the same row on demand; parsing it is the same answer, earlier.
- a present `archive` mapping and a `modules` list in one cohort contradict each other and
  are an error naming both keys, rather than one of them silently winning.
- A unit's `required_level` is carried only when the unit or one of its module
  ancestors declares one. The course's own level is not pushed down, so
  `default_unit_required_level` still answers for a unit that declares nothing
  (`Unit.effective_required_level`).
- Instructor references resolve against a `person` collection of the same
  repository when there is one, and otherwise carry the reference itself as the
  instructor slug, which is what the importer matches an existing host by.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

from community_base.content_sync.documents import (
    Collection,
    Diagnostic,
    ParsedDocument,
    ReadResult,
    read_repository,
)
from community_base.content_sync.kinds.base import resolve_level
from community_base.curriculum.code_annotations import (
    CodeAnnotationError,
    validate_annotated_body,
)
from community_base.curriculum.source import (
    FORMAT_MODULES,
    MODE_COHORT,
    MODE_SELF_PACED,
    CohortGraph,
    CourseGraph,
    CurriculumParseError,
    InstructorGraph,
    ModuleGraph,
    ParsedCurriculum,
    UnitGraph,
    validate_module_tree,
)

#: One parser, one version. It names the format, not a site.
PARSER_VERSION = "course-format-1"

#: The `content.yaml` version this parser reads (section 3.1).
SCHEMA_VERSION = 1

COURSE_KIND = "course"
README = "README.md"
SELF_PACED_SLUG = "self-paced"
DELIVERY_MODES = {"live": MODE_COHORT, "self_paced": MODE_SELF_PACED}
PUBLISHED = "published"


def read_courses(source: Any) -> ReadResult:
    """Read one repository once; every course collection comes from this call."""

    return read_repository(source)


def course_collections(result: ReadResult) -> tuple[Collection, ...]:
    """The `course` collections this repository declares, in manifest order."""

    return tuple(item for item in result.collections if item.kind.name == COURSE_KIND)


def parse_course_repository(source: Any, *, path: str | None = None) -> ParsedCurriculum:
    """Read and parse one course collection, for a caller holding no read result.

    `path` names the collection when the repository declares more than one.
    """

    result = read_courses(source)
    collections = course_collections(result)
    if path is not None:
        collections = tuple(item for item in collections if item.path == path)
    if not collections:
        raise CurriculumParseError(
            f"{result.root}: no course collection{'' if path is None else f' at {path!r}'}"
        )
    if len(collections) > 1:
        declared = ", ".join(item.path or "." for item in collections)
        raise CurriculumParseError(f"{result.root}: name one of the course collections: {declared}")
    return parse_course(result, collections[0], commit_sha=getattr(source, "commit_sha", None))


def parse_course(
    result: ReadResult, collection: Collection, *, commit_sha: str | None = None
) -> ParsedCurriculum:
    """One course collection of an already-read repository, as the shared graph."""

    check_read(result, collection)
    documents = [item for item in result.documents if item.collection.index == collection.index]
    course_document = _one_course(documents, collection)
    by_parent: dict[str | None, list[ParsedDocument]] = {}
    for document in documents:
        by_parent.setdefault(document.raw.parent, []).append(document)

    modules = _module_graphs(result, by_parent, parent=course_document.raw.path, inherited=None)
    validate_module_tree(modules, where=collection.path or ".")
    course = _course_graph(result, course_document, documents, modules)
    return ParsedCurriculum(
        parser_version=PARSER_VERSION,
        schema_version=SCHEMA_VERSION,
        commit_sha=commit_sha or None,
        course=course,
    )


def check_read(result: ReadResult, collection: Collection | None = None) -> None:
    """Raise when the toolkit rejected the repository, or this collection of it.

    A read error is never worked around here: the file, the pointer and the
    rule number come from the toolkit, and a retired key such as `prev_url` is
    named by the diagnostic that rejected it rather than by a second rule
    written in this module.
    """

    errors = [item for item in result.errors if _in_scope(item, collection)]
    if errors:
        listed = "\n".join(item.render() for item in errors)
        raise CurriculumParseError(listed)


def _in_scope(diagnostic: Diagnostic, collection: Collection | None) -> bool:
    if collection is None or not collection.path:
        return True
    if diagnostic.path == "content.yaml":
        return True
    return diagnostic.path.startswith(f"{collection.path}/")


def _one_course(documents: Iterable[ParsedDocument], collection: Collection) -> ParsedDocument:
    found = [item for item in documents if item.part.name == "course"]
    if len(found) != 1:  # pragma: no cover -- the layout reports both cases first
        raise CurriculumParseError(
            f"{collection.path or '.'}: expected one course.yaml, found {len(found)}"
        )
    return found[0]


# --- the course ---------------------------------------------------------------


def _course_graph(
    result: ReadResult,
    document: ParsedDocument,
    documents: list[ParsedDocument],
    modules: tuple[ModuleGraph, ...],
) -> CourseGraph:
    values = document.values
    status = values.get("status") or PUBLISHED
    title = document.title
    cohorts = _cohort_graphs(documents, modules, course_title=title)
    return CourseGraph(
        content_id=document.content_id,
        slug=document.slug,
        title=title,
        source_path=document.raw.path,
        description=values.get("description") or "",
        cover_image_url=values.get("image") or "",
        required_level=document.required_level,
        default_unit_required_level=resolve_level(values.get("default_unit_required_level")),
        status=status,
        discussion_url=values.get("discussion_url") or "",
        tags=tuple(values.get("tags") or ()),
        testimonials=tuple(values.get("testimonials") or ()),
        github_repo_url=values.get("repository_url") or "",
        docs_url=values.get("docs_url") or "",
        faq_url=values.get("faq_url") or "",
        hashtag=values.get("hashtag") or "",
        visible=status == PUBLISHED,
        instructors=_instructors(result, values.get("instructors") or ()),
        modules=modules,
        cohorts=cohorts,
    )


def _instructors(result: ReadResult, references: Iterable[Any]) -> tuple[InstructorGraph, ...]:
    people = {item.path: item for item in result.by_kind("person")}
    found: list[InstructorGraph] = []
    for reference in references:
        if not isinstance(reference, str) or not reference:
            continue
        target = reference.split(":", 1)[-1]
        person = people.get(target)
        if person is None:
            found.append(InstructorGraph(name=target, slug=target))
            continue
        found.append(
            InstructorGraph(name=person.title, slug=target, bio=person.values.get("summary") or "")
        )
    return tuple(found)


# --- the module tree ----------------------------------------------------------


def _module_graphs(
    result: ReadResult,
    by_parent: Mapping[str | None, list[ParsedDocument]],
    *,
    parent: str,
    inherited: int | None,
) -> tuple[ModuleGraph, ...]:
    children = [item for item in by_parent.get(parent, ()) if item.part.name == "module"]
    children.sort(key=lambda item: item.sort_key)
    return tuple(_module_graph(result, by_parent, item, inherited) for item in children)


def _module_graph(
    result: ReadResult,
    by_parent: Mapping[str | None, list[ParsedDocument]],
    document: ParsedDocument,
    inherited: int | None,
) -> ModuleGraph:
    values = document.values
    level = resolve_level(document.data.get("required_level"))
    if level is None:
        level = inherited
    units = [item for item in by_parent.get(document.raw.path, ()) if item.part.name == "unit"]
    units.sort(key=lambda item: item.sort_key)
    return ModuleGraph(
        content_id=document.content_id,
        slug=document.slug,
        title=document.title,
        source_path=document.raw.path,
        overview=_overview(result, document),
        sort_order=document.sort_order,
        is_bonus=bool(values.get("is_bonus")),
        available_after_days=values.get("available_after_days"),
        units=tuple(_unit_graph(item, level) for item in units),
        children=_module_graphs(result, by_parent, parent=document.raw.path, inherited=level),
    )


def _overview(result: ReadResult, document: ParsedDocument) -> str:
    """A module's `README.md`, the one place section 3.2 reads one for a course."""

    directory = document.raw.path.rsplit("/", 1)[0]
    path = f"{directory}/{README}" if directory else README
    repository = result.repository
    if repository is None or path not in repository.files:
        return ""
    return repository.read_text(path)


def _unit_graph(document: ParsedDocument, inherited: int | None) -> UnitGraph:
    values = document.values
    body = document.body
    _check_annotations(document.raw.path, body)
    return UnitGraph(
        content_id=document.content_id,
        slug=document.slug,
        title=document.title,
        source_path=document.raw.path,
        body=body,
        video_url=values.get("video_url") or "",
        timestamps=tuple(values.get("timestamps") or ()),
        required_level=_declared_level(document, inherited),
        sort_order=document.sort_order,
        kind=values.get("kind") or "lesson",
        session_position=values.get("session_position"),
        is_bonus=bool(values.get("is_bonus")),
    )


def _declared_level(document: ParsedDocument, inherited: int | None) -> int | None:
    """The unit's own level, else the one its module ancestors declared.

    Section 3.3 inherits `required_level` from the parent item. The course sits
    at the top of that chain, and a unit that takes the course's level must
    stay `None` here so that `Course.default_unit_required_level` still answers
    for it (`Unit.effective_required_level`).
    """

    declared = resolve_level(document.data.get("required_level"))
    return inherited if declared is None else declared


def _check_annotations(path: str, body: str) -> None:
    """Reject a malformed structured code annotation before anything is written."""

    try:
        validate_annotated_body(body, path)
    except CodeAnnotationError as error:
        raise CurriculumParseError(str(error)) from None


# --- cohorts and their placements ---------------------------------------------


def _cohort_graphs(
    documents: Iterable[ParsedDocument],
    modules: tuple[ModuleGraph, ...],
    *,
    course_title: str,
) -> tuple[CohortGraph, ...]:
    found = [item for item in documents if item.part.name == "cohort"]
    found.sort(key=lambda item: item.slug)
    refs = {module.slug: module.content_id or module.slug for module in modules}
    cohorts = tuple(_cohort_graph(item, refs, course_title=course_title) for item in found)
    if cohorts:
        return cohorts
    return (
        CohortGraph(
            content_id=None,
            slug=SELF_PACED_SLUG,
            title=f"{course_title} (self-paced)",
            mode=MODE_SELF_PACED,
            curriculum_format=FORMAT_MODULES,
            source_path=None,
            module_refs=None,
        ),
    )


def _cohort_graph(
    document: ParsedDocument, refs: Mapping[str, str], *, course_title: str
) -> CohortGraph:
    values = document.values
    path = document.raw.path
    identifier = document.slug
    status = values.get("status") or PUBLISHED
    delivery = values.get("delivery")
    # Decision D38: `archive` is a mapping, so presence is what makes a cohort
    # archived; an empty mapping archives it as much as one with a notice path.
    # The file is read rather than `values`, whose default for a mapping key is
    # `{}` and would make every cohort look archived.
    archive = document.data.get("archive") is not None
    declared = document.data.get("modules")
    if archive and declared:
        raise CurriculumParseError(
            f"{path}: archive and modules are both declared; an archived cohort places nothing"
        )
    start_date = _date(values.get("start_date"), path, "/start_date")
    end_date = _date(values.get("end_date"), path, "/end_date")
    if delivery == "live" and status == PUBLISHED and not (start_date and end_date):
        raise CurriculumParseError(
            f"{path}: a published live cohort declares start_date and end_date"
        )
    return CohortGraph(
        content_id=document.content_id,
        slug=identifier,
        title=values.get("title") or f"{course_title} {identifier}",
        mode=DELIVERY_MODES.get(delivery, MODE_COHORT),
        curriculum_format=FORMAT_MODULES,
        start_date=start_date,
        end_date=end_date,
        registration_url=values.get("registration_url") or "",
        hashtag=values.get("hashtag") or "",
        visible=status == PUBLISHED,
        source_path=path,
        module_refs=_placements(path, declared, refs, archive=archive),
        homework_bindings=_bindings(path, values.get("homework") or (), refs),
    )


def _placements(
    path: str, declared: Any, refs: Mapping[str, str], *, archive: bool
) -> tuple[str, ...] | None:
    """Section 3.8: an absent `modules` is the whole tree, `archive` places nothing."""

    if archive:
        return ()
    if declared is None:
        return None
    placed: list[str] = []
    for index, slug in enumerate(declared):
        ref = refs.get(slug)
        if ref is None:
            raise CurriculumParseError(
                f"{path}:/modules/{index}: no top-level module with the slug {slug!r}"
            )
        placed.append(ref)
    return tuple(placed)


def _bindings(
    path: str, declared: Iterable[Any], refs: Mapping[str, str]
) -> tuple[Mapping[str, Any], ...]:
    """The cohort's homework bindings, which `C7.11` reads the manifests of."""

    found: list[Mapping[str, Any]] = []
    for index, entry in enumerate(declared):
        slug = entry.get("module")
        if slug not in refs:
            raise CurriculumParseError(
                f"{path}:/homework/{index}/module: no top-level module with the slug {slug!r}"
            )
        found.append(
            {"module": slug, "source": entry.get("source"), "unit": entry.get("unit") or None}
        )
    return tuple(found)


def _date(value: Any, path: str, pointer: str) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):  # pragma: no cover -- the key check refuses one
        raise CurriculumParseError(f"{path}:{pointer}: expected a date, not a datetime")
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)
