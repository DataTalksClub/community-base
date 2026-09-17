"""Apply homework manifests to ``cb_coursework`` rows.

The curriculum importer (:mod:`community_base.curriculum.importing`) owns the
course, its module tree and its cohorts; this module owns what a cohort binds
on top of them. It reuses that importer's write path rather than repeating it:
:func:`~community_base.curriculum.importing.write_values` decides
created/updated/unchanged, :func:`~community_base.curriculum.importing.provenance`
fills the all-or-nothing provenance columns and
:func:`~community_base.curriculum.importing.delete_stale` removes the rows a
manifest stopped declaring.

Two rules are this module's own.

- ``initial_state`` is the state a homework is created in, not a state a
  re-import restores. An operator opens and scores a homework after the import,
  and a second sync must not close it again.
- A question's answer is written as the sealed envelope the manifest carried.
  ``Question.correct_answer``, the plaintext column, is cleared on every
  imported row, so a repository-managed answer has exactly one representation.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import transaction

from community_base.coursework.manifests import HomeworkGraph, HomeworkManifestError
from community_base.coursework.models import (
    AnswerTypes,
    Homework,
    HomeworkState,
    Question,
    QuestionTypes,
)
from community_base.curriculum.importing import (
    delete_stale,
    file_checksum,
    provenance,
    write_values,
)
from community_base.curriculum.models import Cohort, Course, Module, Unit

QUESTION_TYPES = {
    "multiple_choice": QuestionTypes.MULTIPLE_CHOICE.value,
    "checkboxes": QuestionTypes.CHECKBOXES.value,
    "free_form": QuestionTypes.FREE_FORM.value,
    "free_form_long": QuestionTypes.FREE_FORM_LONG.value,
}
ANSWER_TYPES = {
    None: None,
    "any": AnswerTypes.ANY.value,
    "float": AnswerTypes.FLOAT.value,
    "integer": AnswerTypes.INTEGER.value,
    "exact_string": AnswerTypes.EXACT_STRING.value,
    "contains_string": AnswerTypes.CONTAINS_STRING.value,
}
HOMEWORK_STATES = {
    "closed": HomeworkState.CLOSED.value,
    "open": HomeworkState.OPEN.value,
    "scored": HomeworkState.SCORED.value,
}
FORM_FIELDS = {
    "homework_url": "homework_url_field",
    "time_spent_lectures": "time_spent_lectures_field",
    "time_spent_homework": "time_spent_homework_field",
    "faq_contribution": "faq_contribution_field",
    "learning_in_public_cap": "learning_in_public_cap",
}


def apply_homework_graphs(
    course: Course, graphs: Iterable[HomeworkGraph], *, commit: str, checkout
) -> dict:
    """Write one course's bound homework, idempotently, in one transaction."""

    counts = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0}
    seen: set[str] = set()
    with transaction.atomic():
        for graph in graphs:
            homework = _apply(course, graph, commit, checkout, counts)
            if graph.content_id:
                seen.add(graph.content_id)
            counts["deleted"] += delete_stale(
                Question.objects.filter(homework=homework).exclude(
                    source_content_id__isnull=True
                ),
                {question.content_id for question in graph.questions},
            )
        counts["deleted"] += delete_stale(
            Homework.objects.filter(cohort__course=course).exclude(
                source_content_id__isnull=True
            ),
            seen,
        )
    return counts


def _apply(course: Course, graph: HomeworkGraph, commit, checkout, counts: dict) -> Homework:
    cohort = Cohort.objects.filter(course=course, slug=graph.cohort_slug).first()
    if cohort is None:  # pragma: no cover -- the parser applied the cohort first
        raise HomeworkManifestError(f"{graph.source_path}: no cohort {graph.cohort_slug!r}")
    homework = _homework(cohort, graph)
    if homework.pk is None:
        homework.state = HOMEWORK_STATES[graph.initial_state]
    counts[write_values(homework, _homework_values(course, cohort, graph, commit, checkout))] += 1
    for question_graph in graph.questions:
        question = _question(homework, question_graph)
        counts[
            write_values(question, _question_values(question_graph, graph, commit, checkout))
        ] += 1
    return homework


def _homework(cohort: Cohort, graph: HomeworkGraph) -> Homework:
    homework = None
    if graph.content_id:
        homework = Homework.objects.filter(
            cohort=cohort, source_content_id=graph.content_id
        ).first()
    if homework is None:
        homework = Homework.objects.filter(cohort=cohort, slug=graph.slug).first()
    if homework is None:
        homework = Homework(cohort=cohort, slug=graph.slug)
    homework.source_content_id = graph.content_id
    return homework


def _question(homework: Homework, graph) -> Question:
    question = Question.objects.filter(
        homework=homework, source_content_id=graph.content_id
    ).first()
    if question is None:
        question = Question.objects.filter(
            homework=homework, source_question_id=graph.stable_id
        ).first()
    if question is None:
        question = Question(homework=homework)
    question.source_content_id = graph.content_id
    return question


def _homework_values(course: Course, cohort: Cohort, graph: HomeworkGraph, commit, checkout):
    module = Module.objects.filter(
        course=course, parent__isnull=True, slug=graph.module_slug
    ).first()
    unit = None
    if graph.unit_content_id:
        unit = Unit.objects.filter(
            module__course=course, source_content_id=graph.unit_content_id
        ).first()
    values = {
        "slug": graph.slug,
        "title": graph.title,
        "module": module,
        "unit": unit,
        "instructions_markdown": graph.instructions_markdown,
        "instructions_source_path": graph.instructions_source_path,
        "due_date": graph.due_at,
        **_form_values(graph),
        **provenance(graph.source_path, commit, file_checksum(checkout, graph.source_path)),
    }
    return values


def _form_values(graph: HomeworkGraph) -> dict:
    """The five form keys, each falling back to the model's own default."""

    values = {}
    for name, field in FORM_FIELDS.items():
        declared = getattr(graph.form, name)
        if declared is None:
            declared = Homework._meta.get_field(field).default
        values[field] = declared
    return values


def _question_values(graph, homework_graph: HomeworkGraph, commit, checkout) -> dict:
    return {
        "source_question_id": graph.stable_id,
        "text": graph.prompt,
        "question_type": QUESTION_TYPES[graph.type],
        "answer_type": ANSWER_TYPES[graph.answer_type],
        "possible_answers": "\n".join(option.label for option in graph.options) or None,
        "source_option_ids": [option.id for option in graph.options] or None,
        "answer_envelope": dict(graph.answer) if graph.answer is not None else None,
        "correct_answer": None,
        "scores_for_correct_answer": graph.points,
        **provenance(
            homework_graph.source_path,
            commit,
            file_checksum(checkout, homework_graph.source_path),
        ),
    }
