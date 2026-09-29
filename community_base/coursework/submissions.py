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


def submit_homework(homework, user, *, answers_by_question_id) -> Submission | None:
    """Create or update the learner's homework submission; ``None`` when rejected.

    Get-or-creates the cohort enrollment through
    ``leaderboard.ensure_enrollment``; whether the request is allowed to
    create one is the view's job (POST-only semantics). When the homework
    state is not ``OPEN`` the donor records ``homework.submission_rejected``
    with reason ``"closed"`` and saves nothing further; the package fires
    ``COURSEWORK_HOMEWORK_SUBMISSION_REJECTED`` and returns ``None``.
    A self-paced homework (``Homework.reveals_on_submit``) accepts one submission per learner:
    its answers are revealed on submit, so a second one is rejected with reason
    ``"already_submitted"``. Otherwise the learner's ``Submission`` is created or refreshed with
    ``submitted_at``, one ``Answer`` is updated or created per answered
    question (question ids outside this homework are ignored), the score is
    recomputed through ``scoring.update_score``, and
    ``COURSEWORK_HOMEWORK_SUBMITTED`` fires with the submission.
    """

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
    with transaction.atomic():
        submission = Submission.objects.filter(homework=homework, student=user).first()
        if submission is None:
            submission = Submission(homework=homework, student=user, enrollment=enrollment)
        submission.submitted_at = timezone.now()
        submission.full_clean()
        submission.save()

        for question in homework.questions.order_by("id"):
            if str(question.id) not in answers:
                continue
            Answer.objects.update_or_create(
                submission=submission,
                question=question,
                defaults={"answer_text": answers[str(question.id)]},
            )

        update_score(submission, list(submission.answers.select_related("question")))
        if homework.reveals_on_submit:
            # Scored for this learner on submit: it counts on the leaderboard at once, with no
            # operator scoring pass (#323).
            update_leaderboard(homework.cohort)

    coursework_hooks.homework_submitted(submission=submission)
    return submission


def homework_form_context(homework, user, *, action: str = "") -> dict:
    """The context `coursework/_homework_form.html` needs, for either page it sits on.

    The homework page and a bound unit's page (`FORMAT.md` section 3.8) show
    the same form, so they read the same questions, the same existing answers
    and the same open/closed state from here rather than each building their
    own. `action` is where the form posts; empty means the page it is on.
    """

    questions = list(homework.questions.order_by("id"))
    submission = None
    if user.is_authenticated:
        submission = (
            Submission.objects.filter(homework=homework, student=user)
            .select_related("enrollment")
            .first()
        )
    accepting = homework.state == HomeworkState.OPEN.value
    if locked_after_submit(homework, submission):
        accepting = False
    answers = (
        {answer.question_id: answer for answer in submission.answers.all()}
        if submission is not None
        else {}
    )
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
