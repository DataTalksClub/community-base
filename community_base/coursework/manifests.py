"""Homework manifests: a cohort's bindings onto the coursework graph.

`FORMAT.md` section 3.8 puts the gradable assignment in
``cohorts/<identifier>/homework/<module-slug>/homework.yaml`` and binds it from
``cohort.yaml``. The course parser (:mod:`community_base.curriculum.parsers`)
already turned those bindings into ``CohortGraph.homework_bindings``; this
module reads the manifests they name.

It maps and nothing else. The document toolkit
(:mod:`community_base.content_sync.documents`) already walked the course
collection, read every ``homework.yaml`` it found as a ``homework`` part,
applied the core keys of section 3.3 and the part keys the registry declares
(:mod:`community_base.content_sync.kinds.course`), and derived the slug from the
module directory name. Nothing here opens a file, parses YAML or decides
whether a key is allowed: a manifest that breaks one of those rules is already a
located :class:`~community_base.content_sync.documents.Diagnostic` before this
module runs.

What is left is the binding half, which no single file can state on its own:
which manifest a binding points at, whether the cohort places the module it
names, whether the unit it names is a ``kind: homework`` unit of this course,
and whether each encrypted answer was sealed for this course, this homework and
this question. The last of those is
:func:`community_base.coursework.answer_crypto.validate_source_envelope`, the
one envelope check in the package: the reader holds no key, decrypts nothing
and never sees a plaintext answer.

Package rulings, written here because section 3.8 states the manifest by
reference to the DataTalks.Club shape rather than as a key table.

- A choice question (``multiple_choice``, ``checkboxes``) carries ``options``
  and no ``answer_type``; a free-form question carries ``answer_type`` and no
  ``options``. Each is an error naming the key, because the two shapes answer
  different questions and a manifest carrying both says neither.
- ``answer_type: any`` accepts anything, so it carries no ``answer``; every
  other answer type carries one. An answer that is not the envelope -- a
  plaintext ``correct:`` key is the shape the AI Shipping Labs units use -- is
  refused by the registry as an unknown key before this module runs.
- An absent ``form`` key takes the coursework field default rather than a
  default restated here.
"""

from __future__ import annotations

import datetime as dt
import posixpath
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from community_base.content_sync.documents import Collection, ParsedDocument, ReadResult
from community_base.coursework.answer_crypto import (
    HomeworkAnswerCryptoError,
    validate_source_envelope,
)
from community_base.curriculum.source import (
    CohortGraph,
    CurriculumParseError,
    ModuleGraph,
    ParsedCurriculum,
    UnitGraph,
)

HOMEWORK_PART = "homework"
HOMEWORK_UNIT_KIND = "homework"
CHOICE_TYPES = ("multiple_choice", "checkboxes")
ANSWER_TYPE_ANY = "any"
DEFAULT_INSTRUCTIONS = "homework.md"
RULE = "3.8"


@dataclass(frozen=True, slots=True)
class HomeworkOptionGraph:
    id: str
    label: str


@dataclass(frozen=True, slots=True)
class HomeworkQuestionGraph:
    content_id: str
    stable_id: str
    type: str
    prompt: str
    points: int
    options: tuple[HomeworkOptionGraph, ...] = field(default=())
    answer_type: str | None = None
    # The sealed envelope, stored as it was authored. The package never holds
    # the plaintext of a source-managed answer outside a scoring request.
    answer: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class HomeworkFormGraph:
    """Which optional submission fields the form shows; ``None`` keeps the default."""

    homework_url: bool | None = None
    time_spent_lectures: bool | None = None
    time_spent_homework: bool | None = None
    faq_contribution: bool | None = None
    learning_in_public_cap: int | None = None


@dataclass(frozen=True, slots=True)
class HomeworkGraph:
    content_id: str | None
    slug: str
    title: str
    source_path: str
    cohort_slug: str
    module_slug: str
    unit_content_id: str | None
    instructions_source_path: str
    instructions_markdown: str
    due_at: dt.datetime
    initial_state: str
    form: HomeworkFormGraph
    questions: tuple[HomeworkQuestionGraph, ...] = field(default=())


class HomeworkManifestError(CurriculumParseError):
    """A cohort's homework bindings do not satisfy section 3.8."""


def read_cohort_homework(
    result: ReadResult, collection: Collection, parsed: ParsedCurriculum
) -> tuple[HomeworkGraph, ...]:
    """Every manifest the course's cohorts bind, in cohort then binding order."""

    manifests = {
        document.raw.path: document
        for document in result.documents
        if document.collection.index == collection.index and document.part.name == HOMEWORK_PART
    }
    course = parsed.course
    units = {unit.content_id: unit for unit in _units(course.modules) if unit.content_id}
    found: list[HomeworkGraph] = []
    for cohort in course.cohorts:
        placed = _placed_module_slugs(cohort, course.modules)
        for index, binding in enumerate(cohort.homework_bindings):
            found.append(
                _homework_graph(
                    result,
                    cohort,
                    binding,
                    index,
                    manifests=manifests,
                    placed=placed,
                    units=units,
                    course_slug=course.slug,
                )
            )
    return tuple(found)


def _units(modules: Iterable[ModuleGraph]) -> Iterable[UnitGraph]:
    for module in modules:
        yield from module.units
        yield from _units(module.children)


def _placed_module_slugs(cohort: CohortGraph, modules: tuple[ModuleGraph, ...]) -> set[str]:
    """The top-level module slugs this cohort places (section 3.8, `modules`)."""

    if cohort.module_refs is None:
        return {module.slug for module in modules}
    by_ref = {module.content_id or module.slug: module.slug for module in modules}
    return {by_ref[ref] for ref in cohort.module_refs if ref in by_ref}


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


def _due_at(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    # The registry already refused anything else, offset included.
    return dt.datetime.fromisoformat(str(value))


def _form(values: Mapping[str, Any]) -> HomeworkFormGraph:
    return HomeworkFormGraph(
        homework_url=values.get("homework_url"),
        time_spent_lectures=values.get("time_spent_lectures"),
        time_spent_homework=values.get("time_spent_homework"),
        faq_contribution=values.get("faq_contribution"),
        learning_in_public_cap=values.get("learning_in_public_cap"),
    )


def _questions(document: ParsedDocument, *, course_slug: str) -> tuple[HomeworkQuestionGraph, ...]:
    path = document.raw.path
    homework_slug = document.slug
    found: list[HomeworkQuestionGraph] = []
    seen: set[str] = set()
    for index, entry in enumerate(document.values.get("questions") or ()):
        pointer = f"/questions/{index}"
        stable_id = entry["id"]
        if stable_id in seen:
            raise HomeworkManifestError(
                f"{path}:{pointer}/id: [{RULE}] duplicate question id {stable_id!r}"
            )
        seen.add(stable_id)
        question_type = entry["type"]
        options = _options(path, pointer, entry, question_type)
        answer_type = _answer_type(path, pointer, entry, question_type)
        found.append(
            HomeworkQuestionGraph(
                content_id=entry["content_id"],
                stable_id=stable_id,
                type=question_type,
                prompt=entry["prompt"],
                points=entry["points"],
                options=options,
                answer_type=answer_type,
                answer=_answer(
                    path,
                    pointer,
                    entry,
                    answer_type=answer_type,
                    course_slug=course_slug,
                    homework_slug=homework_slug,
                    question_id=stable_id,
                ),
            )
        )
    return tuple(found)


def _options(
    path: str, pointer: str, entry: Mapping[str, Any], question_type: str
) -> tuple[HomeworkOptionGraph, ...]:
    declared = entry.get("options")
    if question_type not in CHOICE_TYPES:
        if declared is not None:
            raise HomeworkManifestError(
                f"{path}:{pointer}/options: [{RULE}] a {question_type} question has no options"
            )
        return ()
    if not declared:
        raise HomeworkManifestError(
            f"{path}:{pointer}/options: [{RULE}] a {question_type} question needs its options"
        )
    options = tuple(HomeworkOptionGraph(id=item["id"], label=item["label"]) for item in declared)
    ids = [option.id for option in options]
    if len(set(ids)) != len(ids):
        raise HomeworkManifestError(f"{path}:{pointer}/options: [{RULE}] option ids are not unique")
    return options


def _answer_type(
    path: str, pointer: str, entry: Mapping[str, Any], question_type: str
) -> str | None:
    declared = entry.get("answer_type")
    if question_type in CHOICE_TYPES:
        if declared is not None:
            raise HomeworkManifestError(
                f"{path}:{pointer}/answer_type: [{RULE}] a {question_type} question is "
                "answered by its options, not by an answer type"
            )
        return None
    if declared is None:
        raise HomeworkManifestError(
            f"{path}:{pointer}/answer_type: [{RULE}] a {question_type} question needs an "
            "answer type"
        )
    return declared


def _answer(
    path: str,
    pointer: str,
    entry: Mapping[str, Any],
    *,
    answer_type: str | None,
    course_slug: str,
    homework_slug: str,
    question_id: str,
) -> Mapping[str, Any] | None:
    declared = entry.get("answer")
    if answer_type == ANSWER_TYPE_ANY:
        if declared is not None:
            raise HomeworkManifestError(
                f"{path}:{pointer}/answer: [{RULE}] an answer_type: any question is not scored "
                "and carries no answer"
            )
        return None
    if declared is None:
        raise HomeworkManifestError(
            f"{path}:{pointer}/answer: [{RULE}] the correct answer is required, as the "
            "encrypted envelope of coursework/answer_crypto.py"
        )
    try:
        validate_source_envelope(
            declared,
            course_slug=course_slug,
            homework_slug=homework_slug,
            question_id=question_id,
        )
    except HomeworkAnswerCryptoError as error:
        raise HomeworkManifestError(f"{path}:{pointer}/answer: [{RULE}] {error}") from None
    return dict(declared)
