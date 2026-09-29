"""Learner homework submission service.

Donor mapping: ``courses/views/homework.py`` (the learner homework page and
its POST pipeline), ``courses/views/homework_submission.py`` (submission and
answer persistence with ``submitted_at``) and
``courses/views/homework_post_preview.py`` (the state guard that rejects
POSTs while the homework is not ``OPEN``). The package service is the single
write path for ``Submission`` and ``Answer`` rows; the confirmation email
and the datamailer membership sync stay site-side behind the
``COURSEWORK_HOMEWORK_SUBMITTED`` hook.
"""

import math
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from community_base.coursework.homework_reveal import (
    locked_after_submit,
    question_results,
    results_revealed,
)
from community_base.coursework.hooks import hooks as coursework_hooks
from community_base.coursework.leaderboard import ensure_enrollment, update_leaderboard
from community_base.coursework.models import Answer, HomeworkState, Submission
from community_base.coursework.question_order import ordered_questions
from community_base.coursework.scoring import update_score

CLOSED_HOMEWORK_REASON = "closed"
REVEALED_HOMEWORK_REASON = "already_submitted"


def _rejection_reason(homework, user) -> str | None:
    if homework.state != HomeworkState.OPEN.value:
        return CLOSED_HOMEWORK_REASON
    existing = Submission.objects.filter(homework=homework, student=user).first()
    if locked_after_submit(homework, existing):
        return REVEALED_HOMEWORK_REASON
    return None


def _normalized_answers(answers_by_question_id) -> dict[str, str]:
    return {
        str(question_id): answer_text
        for question_id, answer_text in (answers_by_question_id or {}).items()
    }


def _optional_hours(raw, label):
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValidationError(f"{label} must be a non-negative number of hours.") from None
    if not parsed.is_finite() or parsed < 0:
        raise ValidationError(f"{label} must be a non-negative number of hours.")
    result = float(parsed)
    if not math.isfinite(result):
        raise ValidationError(f"{label} must be a non-negative number of hours.")
    return result


def _public_links(raw, cap):
    if not isinstance(raw, str):
        raise ValidationError("Enter public links one per line.")
    links = []
    for line in raw.splitlines():
        link = line.strip()
        if link:
            links.append(link)
    if len(links) > cap:
        raise ValidationError(f"Add no more than {cap} public links.")
    validator = URLValidator(schemes=["http", "https"])
    for link in links:
        try:
            validator(link)
        except ValidationError:
            raise ValidationError(
                "Enter a valid http or https link for each public link."
            ) from None
    return links


def _stepper_values(homework, final_fields, public_answer):
    values = {}
    if homework.homework_url_field:
        url = final_fields.get("homework_link", "").strip()
        if not url:
            raise ValidationError("Homework URL is required.")
        URLValidator(schemes=["http", "https"])(url)
        values["homework_link"] = url
    for flag, key, label in (
        (homework.time_spent_lectures_field, "time_spent_lectures", "Time spent on lectures"),
        (homework.time_spent_homework_field, "time_spent_homework", "Time spent on homework"),
    ):
        if flag:
            values[key] = _optional_hours(final_fields.get(key, ""), label)
    if homework.learning_in_public_cap > 0:
        values["learning_in_public_links"] = _public_links(
            public_answer, homework.learning_in_public_cap
        )
    return values


def _save_answers(homework, submission, answers):
    for question in ordered_questions(homework):
        identity = str(question.id)
        if identity not in answers:
            continue
        Answer.objects.update_or_create(
            submission=submission,
            question=question,
            defaults={"answer_text": answers[identity]},
        )


def _persist_submission(homework, user, enrollment, answers, extra_values):
    with transaction.atomic():
        submission = Submission.objects.filter(homework=homework, student=user).first()
        if submission is None:
            submission = Submission(homework=homework, student=user, enrollment=enrollment)
        submission.submitted_at = timezone.now()
        for field, value in extra_values.items():
            setattr(submission, field, value)
        submission.full_clean()
        submission.save()
        _save_answers(homework, submission, answers)
        update_score(submission, list(submission.answers.select_related("question")))
        if homework.reveals_on_submit:
            update_leaderboard(homework.cohort)
    return submission


def submit_homework(
    homework, user, *, answers_by_question_id, stepper_fields=None, public_answer=""
) -> Submission | None:
    """Submit through the existing scoring and hook path; return None when rejected."""

    enrollment, _created = ensure_enrollment(homework.cohort, user)

    reason = _rejection_reason(homework, user)
    if reason is not None:
        coursework_hooks.homework_submission_rejected(
            homework=homework,
            enrollment=enrollment,
            reason=reason,
        )
        return None

    answers = _normalized_answers(answers_by_question_id)
    extra_values = {}
    if homework.stepper_enabled and stepper_fields is not None:
        extra_values = _stepper_values(homework, stepper_fields, public_answer)
    submission = _persist_submission(homework, user, enrollment, answers, extra_values)
    coursework_hooks.homework_submitted(submission=submission)
    return submission


def homework_form_context(homework, user, *, action: str = "") -> dict:
    """The context `coursework/_homework_form.html` needs, for either page it sits on.

    The homework page and a bound unit's page (`FORMAT.md` section 3.8) show
    the same form, so they read the same questions, the same existing answers
    and the same open/closed state from here rather than each building their
    own. `action` is where the form posts; empty means the page it is on.
    """

    questions = list(ordered_questions(homework))
    submission = _learner_submission(homework, user)
    accepting = homework.state == HomeworkState.OPEN.value
    if locked_after_submit(homework, submission):
        accepting = False
    answers = _submission_answers(submission)
    results = question_results(homework, submission)
    return {
        "homework": homework,
        "question_answers": [(question, answers.get(question.id)) for question in questions],
        "results_revealed": results_revealed(homework, submission),
        "revealed_rows": _revealed_rows(questions, answers, results),
        "is_authenticated": user.is_authenticated,
        "accepting_submissions": accepting,
        "deadline_passed": _deadline_passed(homework),
        "disabled": not accepting,
        "submission": submission,
        "homework_form_action": action,
    }


def _learner_submission(homework, user):
    if not user.is_authenticated:
        return None
    return (
        Submission.objects.filter(homework=homework, student=user)
        .select_related("enrollment")
        .first()
    )


def _submission_answers(submission):
    if submission is None:
        return {}
    return {answer.question_id: answer for answer in submission.answers.all()}


def _deadline_passed(homework) -> bool:
    """A self-paced homework has no deadline, whatever date it stores (#323)."""

    if homework.reveals_on_submit or homework.due_date is None:
        return False
    return homework.due_date < timezone.now()


def _revealed_rows(questions, answers, results) -> list[tuple]:
    rows = []
    for question in questions:
        if question.id in results:
            rows.append((question, answers.get(question.id), results[question.id]))
    return rows
