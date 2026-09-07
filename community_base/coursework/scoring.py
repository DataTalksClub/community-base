"""Homework submission scoring: questions, FAQ and learning-in-public.

``update_score`` scores one submission (C5.2b); ``score_homework_submissions``
is the donor's batch scoring service (``courses/scoring.py``) that scores a
whole homework, marks it scored and refreshes the leaderboard.
"""

import logging
from collections import defaultdict
from enum import Enum
from time import time

from django.db import transaction
from django.utils import timezone

from community_base.coursework.answer_checks import is_answer_correct
from community_base.coursework.leaderboard import update_leaderboard
from community_base.coursework.models import Answer, Homework, HomeworkState, Submission
from community_base.coursework.statistics import calculate_homework_statistics

logger = logging.getLogger(__name__)


def update_learning_in_public_score(submission: Submission) -> int:
    learning_in_public_score = 0

    if submission.enrollment.disable_learning_in_public:
        submission.learning_in_public_score = 0
        return 0

    if submission.learning_in_public_links:
        learning_in_public_score = len(submission.learning_in_public_links)
        submission.learning_in_public_score = learning_in_public_score

    return learning_in_public_score


def update_faq_score(submission: Submission) -> int:
    faq_score = 0

    if submission.faq_contribution_url and len(submission.faq_contribution_url) >= 5:
        faq_score = 1
        submission.faq_score = faq_score

    return faq_score


def score_answer(answer: Answer, save: bool) -> int:
    is_correct = is_answer_correct(answer.question, answer)
    answer.is_correct = is_correct
    if save:
        answer.save()

    if is_correct:
        return answer.question.scores_for_correct_answer
    return 0


def questions_score(answers: list[Answer], save: bool) -> int:
    return sum(score_answer(answer, save) for answer in answers)


def submission_total_score(submission: Submission, questions_score_value: int):
    lip_score = update_learning_in_public_score(submission)
    faq_score = update_faq_score(submission)
    return questions_score_value + lip_score + faq_score


def update_score(submission: Submission, answers: list[Answer], save: bool = True) -> None:
    logger.info("Scoring submission %s", submission.id)
    score = questions_score(answers, save)
    submission.questions_score = score
    submission.total_score = submission_total_score(submission, score)

    if save:
        submission.save()


class HomeworkScoringStatus(Enum):
    OK = "OK"
    FAIL = "Warning"


def _homework_scoring_error(homework: Homework, homework_id, force: bool) -> str | None:
    if homework.due_date > timezone.now():
        return (
            f"The due date for homework {homework_id} is in the future. "
            "Update the due date to score."
        )
    if homework.state == HomeworkState.CLOSED.value:
        return f"Homework {homework_id} is closed. Update the state to OPEN to score."
    if homework.state == HomeworkState.SCORED.value and not force:
        return f"Homework {homework_id} is already scored."
    return None


def _score_homework_submission_batch(submissions, answers_by_submission_id):
    for submission in submissions:
        update_score(submission, answers_by_submission_id[submission.id], save=False)


def _persist_scored_homework_submissions(homework_id, submissions, answers):
    logger.info("Updating the submissions for homework %s", homework_id)
    Submission.objects.bulk_update(
        submissions,
        ["questions_score", "learning_in_public_score", "faq_score", "total_score"],
    )
    logger.info("Updating answers for homework %s", homework_id)
    Answer.objects.bulk_update(answers, ["is_correct"])


def _mark_homework_scored(homework: Homework):
    homework.state = HomeworkState.SCORED.value
    homework.save(update_fields=["state"])

    cohort = homework.cohort
    update_leaderboard(cohort)

    cohort.first_homework_scored = True
    cohort.save(update_fields=["first_homework_scored"])

    calculate_homework_statistics(homework, force=True)


def score_homework_submissions(
    homework_id,
    force: bool = False,
) -> tuple[HomeworkScoringStatus, str]:
    """Score every submission of one homework (donor ``courses/scoring.py``).

    Preconditions each return ``(FAIL, message)`` without raising: the due date
    is in the future, the homework is closed, or it is already scored without
    ``force``. The donor's observability events map to structured log calls;
    the leaderboard recompute and the homework statistics refresh run inside
    the same transaction.
    """

    with transaction.atomic():
        started_at = time()
        logger.info("Scoring submissions for homework %s", homework_id)

        homework = Homework.objects.get(pk=homework_id)

        if error := _homework_scoring_error(homework, homework_id, force):
            logger.warning(
                "homework.scoring_failed homework=%s reason=%s",
                homework_id,
                error,
            )
            return (HomeworkScoringStatus.FAIL, error)

        submissions = list(
            Submission.objects.filter(homework__id=homework_id).select_related("enrollment")
        )
        answers = list(
            Answer.objects.filter(submission__in=submissions).select_related(
                "question",
                "submission",
            )
        )
        answers_by_submission_id = defaultdict(list)
        for answer in answers:
            answers_by_submission_id[answer.submission_id].append(answer)

        _score_homework_submission_batch(submissions, answers_by_submission_id)
        _persist_scored_homework_submissions(homework_id, submissions, answers)
        _mark_homework_scored(homework)

        duration_ms = int((time() - started_at) * 1000)
        logger.info("homework.scored homework=%s duration_ms=%s", homework_id, duration_ms)
        return (HomeworkScoringStatus.OK, f"Homework {homework_id} is scored")
