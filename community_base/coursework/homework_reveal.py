"""When a learner may see their homework results, and what those results are.

One owner for the reveal policy (#323). A dated cohort's homework reveals nothing until an
operator scores it (``HomeworkState.SCORED``). A self-paced cohort's homework
(``Homework.reveals_on_submit``) is scored for the learner on submit, so their results are
revealed as soon as they have submitted. Correctness comes from ``Answer.is_correct``, which
``scoring.update_score`` sets on every submit and the operator's batch scoring refreshes.
"""

import logging
from dataclasses import dataclass

from community_base.coursework.answer_crypto import HomeworkAnswerCryptoError
from community_base.coursework.models import HomeworkState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HomeworkQuestionResult:
    correct: bool
    correct_answer: str = ""
    explanation: str = ""


def results_revealed(homework, submission) -> bool:
    if submission is None:
        return False
    if homework.reveals_on_submit:
        return True
    return homework.state == HomeworkState.SCORED.value


def locked_after_submit(homework, submission) -> bool:
    """A self-paced learner who has seen the answers cannot submit again."""

    return submission is not None and homework.reveals_on_submit


def _choice_answer_text(question) -> str:
    labels = question.get_possible_answers()
    correct = []
    for index in question.zero_based_correct_answer_indices():
        if 0 <= index < len(labels):
            correct.append(labels[index])
    return ", ".join(correct)


def correct_answer_text(question) -> str:
    """Display text of a question's correct answer; empty when the answer key is unavailable."""

    try:
        if question.has_choice_answers():
            return _choice_answer_text(question)
        return question.resolved_correct_answer()
    except HomeworkAnswerCryptoError:
        logger.warning("homework.reveal_answer_unavailable question=%s", question.pk)
        return ""


def question_results(homework, submission) -> dict[int, HomeworkQuestionResult]:
    """Per-question results keyed by question id, or empty when nothing is revealed yet."""

    if not results_revealed(homework, submission):
        return {}
    correct_by_question = {}
    for answer in submission.answers.all():
        correct_by_question[answer.question_id] = answer.is_correct
    results = {}
    for question in homework.questions.order_by("id"):
        results[question.id] = HomeworkQuestionResult(
            correct=correct_by_question.get(question.id, False),
            correct_answer=correct_answer_text(question),
        )
    return results
