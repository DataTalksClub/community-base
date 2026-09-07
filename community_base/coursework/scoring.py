"""Homework submission scoring: questions, FAQ and learning-in-public.

The batch service ``score_homework_submissions`` is ported from the DTC donor
``courses/scoring.py``. Donor deviations:

- The donor refreshes the leaderboard directly inside ``_mark_homework_scored``
  (``leaderboard.update_leaderboard(course)``); the package fires the
  ``hooks.homework_leaderboard_updater`` hook with the cohort instead, so
  sites wire their own refresh through ``COMMUNITY_BASE``.
- The donor records ``homework.scored`` and ``homework.scoring_failed``
  observability events; the package fires ``hooks.homework_scored`` and
  ``hooks.homework_scoring_failed`` at the same event points.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from time import time

from django.db import transaction
from django.utils import timezone

from community_base.coursework import statistics
from community_base.coursework.answer_checks import is_answer_correct
from community_base.coursework.hooks import hooks
from community_base.coursework.models import Answer, Homework, HomeworkState, Submission

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


@dataclass(frozen=True)
class HomeworkScoringBatch:
    submissions: object
    answers: object
    answers_by_submission_id: dict


def _homework_scoring_error(homework, homework_id, force=False):
    if homework.due_date > timezone.now():
        return f"The due date for {homework_id} is in the future. Update the due date to score."
    if homework.state == HomeworkState.CLOSED.value:
        return f"Homework {homework_id} is closed. Update the state to OPEN to score."
    if homework.state == HomeworkState.SCORED.value and not force:
        return f"Homework {homework_id} is already scored."
    return None


def _answers_by_submission(answers):
    answers_by_submission_id = defaultdict(list)
    for answer in answers:
        answers_by_submission_id[answer.submission_id].append(answer)
    return answers_by_submission_id


def _score_homework_submission_batch(
    submissions,
    answers_by_submission_id,
):
    for submission in submissions:
        submission_answers = answers_by_submission_id[submission.id]
        update_score(submission, submission_answers, save=False)


def _persist_scored_homework_submissions(homework_id, submissions, answers):
    logger.info(f"Updating the submissions for homework {homework_id}")
    Submission.objects.bulk_update(
        submissions,
        [
            "questions_score",
            "learning_in_public_score",
            "faq_score",
            "total_score",
        ],
    )

    logger.info(f"Updating answers for homework {homework_id}")
    Answer.objects.bulk_update(answers, ["is_correct"])


def _homework_scoring_batch(homework_id):
    submissions = Submission.objects.filter(homework__id=homework_id).select_related("enrollment")
    answers = Answer.objects.filter(submission__in=submissions).select_related(
        "question", "submission"
    )
    answers_by_submission_id = _answers_by_submission(answers)
    return HomeworkScoringBatch(
        submissions=submissions,
        answers=answers,
        answers_by_submission_id=answers_by_submission_id,
    )


def _mark_homework_scored(homework):
    homework.state = HomeworkState.SCORED.value
    homework.save()

    cohort = homework.cohort
    # Donor parity: the leaderboard refresh runs inside the scoring
    # transaction; sites wire their implementation through the hook.
    hooks.homework_leaderboard_updater(cohort=cohort)

    cohort.first_homework_scored = True
    cohort.save()

    statistics.calculate_homework_statistics(homework, force=True)


def _homework_scoring_success(homework_id, started_at):
    duration = time() - started_at
    logger.info(f"Scored homework in {duration:.2f} seconds")
    message = f"Homework {homework_id} is scored"
    return (
        HomeworkScoringStatus.OK,
        message,
    )


def _score_and_persist_homework_submissions(homework_id):
    batch = _homework_scoring_batch(homework_id)
    logger.info(
        f"Scoring {len(batch.answers_by_submission_id)} submissions for homework {homework_id}"
    )

    _score_homework_submission_batch(
        batch.submissions,
        batch.answers_by_submission_id,
    )
    _persist_scored_homework_submissions(
        homework_id,
        batch.submissions,
        batch.answers,
    )

    logger.info(f"Scored {len(batch.submissions)} submissions for homework {homework_id}")


def score_homework_submissions(
    homework_id: int | str,
    force: bool = False,
) -> tuple[HomeworkScoringStatus, str]:
    """Score every submission of one homework and close it for scoring.

    Fail-closed: refuses future due dates, closed homework and re-scoring
    without ``force``. Runs atomically like the donor.
    """
    with transaction.atomic():
        t0 = time()
        logger.info(f"Scoring submissions for homework {homework_id}")

        homework = Homework.objects.get(pk=homework_id)

        if error := _homework_scoring_error(homework, homework_id, force):
            hooks.homework_scoring_failed(homework=homework, reason=error)
            return (HomeworkScoringStatus.FAIL, error)

        _score_and_persist_homework_submissions(homework_id)
        _mark_homework_scored(homework)
        hooks.homework_scored(homework=homework, duration_ms=int((time() - t0) * 1000))

        return _homework_scoring_success(homework_id, t0)
