"""Homework graphs and shared question validation for the two source forms.

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
  other answer type carries one. A plaintext ``correct:`` key is refused in
  this cohort manifest schema; the distinct course-tree unit schema accepts it.
- An absent ``form`` key takes the coursework field default rather than a
  default restated here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from community_base.content_sync.documents import Collection, ParsedDocument, ReadResult
from community_base.coursework.answer_crypto import (
    HomeworkAnswerCryptoError,
    validate_source_envelope,
)
from community_base.curriculum.source import (
    CurriculumParseError,
    ParsedCurriculum,
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
    correct: str | None = None
    authored_position: int | None = None
    step_label: str = ""


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
    due_at: dt.datetime | None
    initial_state: str
    form: HomeworkFormGraph
    questions: tuple[HomeworkQuestionGraph, ...] = field(default=())
    course_tree: bool = False
    due_date_override: bool = False
    stepper: bool = False


class HomeworkManifestError(CurriculumParseError):
    """A cohort's homework bindings do not satisfy section 3.8."""


def read_cohort_homework(
    result: ReadResult, collection: Collection, parsed: ParsedCurriculum
) -> tuple[HomeworkGraph, ...]:
    from community_base.coursework.binding_reader import read_cohort_homework as read_bindings

    return read_bindings(result, collection, parsed)


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
    seen_content_ids: set[str] = set()
    for index, entry in enumerate(document.values.get("questions") or ()):
        pointer = f"/questions/{index}"
        stable_id = entry["id"]
        if stable_id in seen:
            raise HomeworkManifestError(
                f"{path}:{pointer}/id: [{RULE}] duplicate question id {stable_id!r}"
            )
        seen.add(stable_id)
        content_id = entry["content_id"]
        if content_id in seen_content_ids:
            raise HomeworkManifestError(
                f"{path}:{pointer}/content_id: [{RULE}] "
                f"duplicate question content_id {content_id!r}"
            )
        seen_content_ids.add(content_id)
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
