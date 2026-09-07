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

from community_base.coursework.hooks import hooks as coursework_hooks
from community_base.coursework.leaderboard import ensure_enrollment
from community_base.coursework.models import Answer, HomeworkState, Submission
from community_base.coursework.scoring import update_score

CLOSED_HOMEWORK_REASON = "closed"


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
    Otherwise the learner's ``Submission`` is created or refreshed with
    ``submitted_at``, one ``Answer`` is updated or created per answered
    question (question ids outside this homework are ignored), the score is
    recomputed through ``scoring.update_score``, and
    ``COURSEWORK_HOMEWORK_SUBMITTED`` fires with the submission.
    """

    enrollment, _created = ensure_enrollment(homework.cohort, user)

    if homework.state != HomeworkState.OPEN.value:
        coursework_hooks.homework_submission_rejected(
            homework=homework,
            enrollment=enrollment,
            reason=CLOSED_HOMEWORK_REASON,
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

    coursework_hooks.homework_submitted(submission=submission)
    return submission
