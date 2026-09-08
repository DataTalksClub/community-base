"""Studio-only coursework operations: admin edits, answer keys, deadline extension.

Ported from the donor ``studio_courses/services.py``,
``studio_courses/deadline_extension.py`` and ``courses/homework_correct_answers.py``.
These operations exist only in the donor's staff surface, so they live beside the
learner services instead of inside them. The leaderboard refresh after an admin
edit is the C5.2da ``update_leaderboard`` rollup, fired only when the total
changed, exactly where the donor calls it.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q

from community_base.coursework.leaderboard import update_leaderboard
from community_base.coursework.models import (
    Answer,
    Homework,
    Question,
    QuestionTypes,
    Submission,
)

# Single source of truth for the deadline-extension choices offered in Studio.
EXTENSION_OPTIONS = (
    (1, "1 day"),
    (3, "3 days"),
    (7, "1 week"),
)
ALLOWED_EXTENSION_DAYS = {days for days, _label in EXTENSION_OPTIONS}


def extension_label(days: int) -> str:
    for option_days, label in EXTENSION_OPTIONS:
        if option_days == days:
            return label
    return f"{days} days"


def parse_extension_days(raw_days) -> int | None:
    """Return the requested extension in days, or ``None`` when it is invalid."""

    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return None
    if days not in ALLOWED_EXTENSION_DAYS:
        return None
    return days


def extend_deadlines(obj, date_fields, days: int):
    """Push the given date fields on ``obj`` forward and return the object.

    Shared by the homework and project deadline actions. Homework passes a
    single field; projects pass both deadlines so one action moves them
    together while preserving their spacing.
    """

    delta = timedelta(days=days)
    for field in date_fields:
        setattr(obj, field, getattr(obj, field) + delta)
    obj.save(update_fields=list(date_fields))
    return obj


def most_common_answer_text(question: Question) -> str | None:
    most_common = (
        Answer.objects.filter(
            question=question,
            answer_text__isnull=False,
        )
        .exclude(answer_text__exact="")
        .values("answer_text")
        .annotate(count=Count("id"))
        .order_by("-count")
        .first()
    )
    if most_common is None:
        return None
    return most_common["answer_text"]


def _is_choice_question(question: Question) -> bool:
    return question.question_type in {
        QuestionTypes.MULTIPLE_CHOICE.value,
        QuestionTypes.CHECKBOXES.value,
    }


def _correct_answer_indices(question: Question) -> list[int] | None:
    try:
        return sorted(question.get_correct_answer_indices())
    except ValueError:
        return None


def has_invalid_correct_answer_indices(question: Question) -> bool:
    """Whether a choice question's stored answer names missing options."""

    if not _is_choice_question(question):
        return False
    possible_answers = question.get_possible_answers()
    if not possible_answers:
        return False
    indices = _correct_answer_indices(question)
    if indices is None:
        return True
    return any(index < 1 or index > len(possible_answers) for index in indices)


def fill_most_common_answer_as_correct(question: Question) -> bool:
    """Set one question's correct answer to the most popular one; True when written.

    A question that already carries a usable answer key is left alone. The
    value being set is the answer key, so nothing here logs the question text
    or the answer itself.
    """

    if question.correct_answer and not has_invalid_correct_answer_indices(question):
        return False
    answer = most_common_answer_text(question)
    if answer is None:
        return False
    question.correct_answer = answer
    question.save(update_fields=["correct_answer"])
    return True


def fill_correct_answers(homework: Homework) -> int:
    """Set every unanswered question's key to the most popular answer."""

    updated = 0
    for question in homework.questions.all():
        if fill_most_common_answer_as_correct(question):
            updated += 1
    return updated


def clear_correct_answers(homework: Homework) -> int:
    return homework.questions.update(correct_answer="")


def save_correct_answers_from_admin(homework: Homework, post) -> None:
    """Write the per-question keys posted from the submissions page.

    Choice questions join their posted option indices with commas; the answer
    type falls back to unset when the field is empty.
    """

    for question in homework.questions.order_by("id"):
        field = f"correct_answer_{question.id}"
        if question.has_choice_answers():
            correct_answer = ",".join(post.getlist(field))
        else:
            correct_answer = post.get(field, "")
        answer_type = post.get(f"answer_type_{question.id}", "")
        question.correct_answer = correct_answer
        question.answer_type = answer_type or None
        question.save(update_fields=["correct_answer", "answer_type"])


@transaction.atomic
def update_homework_submission_from_admin(
    submission: Submission,
    *,
    answers_by_question,
    learning_in_public_links,
    faq_contribution_url: str,
    faq_score: int | None,
) -> bool:
    """Apply the admin edit to one submission; return whether the total changed.

    Donor parity: one ``Answer`` upsert per question, the link list replaced,
    the standard scoring pass re-run, then the admin FAQ-score override with a
    recomputed total. The leaderboard rollup runs only when the total changed.
    """

    from community_base.coursework.scoring import update_score

    old_total_score = submission.total_score
    for question, answer_text in answers_by_question:
        Answer.objects.update_or_create(
            submission=submission,
            question=question,
            defaults={"answer_text": answer_text},
        )
    submission.learning_in_public_links = learning_in_public_links
    submission.faq_contribution_url = faq_contribution_url
    updated_answers = list(Answer.objects.filter(submission=submission).select_related("question"))
    update_score(submission, updated_answers, save=True)
    if faq_score is not None:
        submission.faq_score = faq_score
    submission.total_score = (
        submission.questions_score + submission.learning_in_public_score + submission.faq_score
    )
    submission.save(
        update_fields=[
            "learning_in_public_links",
            "faq_contribution_url",
            "faq_score",
            "total_score",
        ]
    )
    score_changed = submission.total_score != old_total_score
    if score_changed:
        update_leaderboard(submission.homework.cohort)
    return score_changed


def homework_submissions_queryset(homework: Homework, search_query: str):
    """Submissions of one homework, newest first, optionally searched.

    The donor searches the student's email or username; the package account
    identifies by email, so the second matcher is the enrollment display name.
    """

    submissions = (
        Submission.objects.filter(homework=homework)
        .select_related("student", "enrollment")
        .order_by("-submitted_at")
    )
    search_query = (search_query or "").strip()
    if search_query:
        submissions = submissions.filter(
            Q(student__email__icontains=search_query)
            | Q(enrollment__display_name__icontains=search_query)
        )
    return submissions


@dataclass(frozen=True)
class CohortHomeworkRow:
    homework: Homework
    submissions_count: int
    can_score: bool
    can_extend_deadline: bool


def cohort_homework_rows(cohort) -> list[CohortHomeworkRow]:
    """Homeworks of one cohort with the admin action flags, due-date order."""

    from community_base.coursework.models import HomeworkState

    counted = (
        Homework.objects.filter(cohort=cohort)
        .annotate(submissions_count=Count("submissions"))
        .order_by("due_date")
    )
    rows = []
    for homework in counted:
        rows.append(
            CohortHomeworkRow(
                homework=homework,
                submissions_count=homework.submissions_count,
                can_score=homework.state in {HomeworkState.OPEN.value, HomeworkState.CLOSED.value},
                can_extend_deadline=homework.state == HomeworkState.OPEN.value,
            )
        )
    return rows


def cohort_support_metrics(cohort) -> dict:
    """The cohort support counters shown on the admin page."""

    from community_base.coursework.models import LeaderboardComplaint

    enrollments = cohort.enrollments.all()
    return {
        "total_enrollments": enrollments.count(),
        "disabled_lip": enrollments.filter(disable_learning_in_public=True).count(),
        "zero_score": enrollments.filter(total_score=0).count(),
        "hidden_leaderboard": enrollments.filter(display_on_leaderboard=False).count(),
        "open_complaints": LeaderboardComplaint.objects.filter(
            enrollment__cohort=cohort, resolved=False
        ).count(),
    }
