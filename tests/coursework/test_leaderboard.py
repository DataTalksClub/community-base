"""Leaderboard rollup, read model, preferences, complaints and batch scoring."""

import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.enrollment_flags import set_learning_in_public_disabled
from community_base.coursework.leaderboard import (
    current_student_leaderboard_enrollment,
    ensure_enrollment,
    file_leaderboard_complaint,
    get_leaderboard_data,
    leaderboard_context,
    resolve_leaderboard_complaint,
    set_enrollment_preference,
    update_leaderboard,
)
from community_base.coursework.models import (
    Answer,
    AnswerTypes,
    HomeworkState,
    HomeworkStatistics,
    LeaderboardComplaint,
    ProjectSubmission,
    QuestionTypes,
    Submission,
)
from community_base.coursework.random_names import ensure_display_name
from community_base.coursework.scoring import (
    HomeworkScoringStatus,
    score_homework_submissions,
)
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import coursework_cohort, homework, question

pytestmark = pytest.mark.django_db


def make_enrollment(cohort, email, **enrollment_values):
    user = User.objects.create_user(email=email)
    return Enrollment.objects.create(user=user, cohort=cohort, **enrollment_values)


def make_submission(cohort, hw, email, **submission_values):
    user = User.objects.create_user(email=email)
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    submission = Submission.objects.create(
        homework=hw, student=user, enrollment=enrollment, **submission_values
    )
    return enrollment, submission


def make_project_submission(project, enrollment, **submission_values):
    return ProjectSubmission.objects.create(
        project=project,
        student=enrollment.user,
        enrollment=enrollment,
        github_link="https://github.com/example/project",
        commit_id="0" * 40,
        **submission_values,
    )


def test_update_leaderboard_ranks_with_id_tiebreak():
    cohort = coursework_cohort()
    hw = homework(cohort)
    q1 = question(
        hw,
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=AnswerTypes.EXACT_STRING.value,
        correct_answer="x",
        scores_for_correct_answer=2,
    )
    project = cohort.projects.create(
        slug="proj1",
        title="Project 1",
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
        peer_review_due_date=timezone.now() + datetime.timedelta(days=2),
    )
    first, first_submission = make_submission(cohort, hw, "first@example.com")
    Answer.objects.create(submission=first_submission, question=q1, answer_text="x")
    first_submission.questions_score = 2
    first_submission.total_score = 2
    first_submission.save()
    second_enrollment = make_enrollment(cohort, "second@example.com")
    make_project_submission(
        project,
        second_enrollment,
        project_score=2,
        total_score=2,
    )

    update_leaderboard(cohort)

    first.refresh_from_db()
    second = second_enrollment
    second.refresh_from_db()
    assert first.total_score == 2
    assert second.total_score == 2
    assert first.position_on_leaderboard == 1
    assert second.position_on_leaderboard == 2


def make_scored_submission(cohort, enrollment, total_score):
    """Score a submission; the rollup reads Submission rows, not Enrollment totals."""

    hw = homework(cohort)
    return Submission.objects.create(
        homework=hw,
        student=enrollment.user,
        enrollment=enrollment,
        total_score=total_score,
    )


def test_hidden_enrollments_stay_ranked_but_unlisted():
    cohort = coursework_cohort()
    hidden = make_enrollment(cohort, "hidden@example.com", display_on_leaderboard=False)
    make_scored_submission(cohort, hidden, 10)
    visible = make_enrollment(cohort, "visible@example.com")
    make_scored_submission(cohort, visible, 4)

    update_leaderboard(cohort)

    hidden.refresh_from_db()
    visible.refresh_from_db()
    assert hidden.total_score == 10
    assert hidden.position_on_leaderboard == 1
    assert visible.position_on_leaderboard == 2

    data = get_leaderboard_data(
        cohort,
        current_student_leaderboard_enrollment(cohort, AnonymousUser()),
    )
    assert [row["id"] for row in data] == [visible.id]


def test_leaderboard_rebuilds_when_current_student_missing():
    cohort = coursework_cohort()
    stale = make_enrollment(cohort, "stale@example.com")
    make_scored_submission(cohort, stale, 5)
    get_leaderboard_data(cohort, current_student_leaderboard_enrollment(cohort, AnonymousUser()))

    newcomer = make_enrollment(cohort, "newcomer@example.com")
    make_scored_submission(cohort, newcomer, 7)
    update_leaderboard(cohort)

    student = current_student_leaderboard_enrollment(cohort, newcomer.user)
    data = get_leaderboard_data(cohort, student)
    assert [row["id"] for row in data] == [newcomer.id, stale.id]
    assert newcomer.position_on_leaderboard == 1


def test_leaderboard_context_finds_current_student_page():
    cohort = coursework_cohort()
    mine = make_enrollment(cohort, "mine@example.com", total_score=1)
    mine.position_on_leaderboard = 1
    mine.save()

    context = leaderboard_context(cohort, mine.user, None)

    assert context["current_student_enrollment_id"] == mine.id
    assert context["current_student_page_number"] == 1
    assert [row["id"] for row in context["page_obj"]] == [mine.id]


def test_complaint_lifecycle_persists_reporter_and_resolver():
    cohort = coursework_cohort()
    enrollment = make_enrollment(cohort, "complained@example.com")
    reporter = User.objects.create_user(email="reporter@example.com")
    staff = User.objects.create_user(email="staff@example.com")

    complaint = file_leaderboard_complaint(
        enrollment,
        reporter,
        issue_type=LeaderboardComplaint.IssueType.OTHER.value,
        description="Score looks wrong",
    )

    assert complaint.reporter == reporter
    assert complaint.resolved is False

    resolve_leaderboard_complaint(complaint, staff)

    complaint.refresh_from_db()
    assert complaint.resolved is True
    assert complaint.resolved_by == staff
    assert complaint.resolved_at is not None


def test_ensure_display_name_prefers_configured_generator(settings):
    settings.COMMUNITY_BASE = {
        "COURSEWORK_DISPLAY_NAME_GENERATOR": lambda enrollment, **kwargs: "Shy Learner",
    }
    cohort = coursework_cohort()
    blank = make_enrollment(cohort, "blank@example.com")

    assert ensure_display_name(blank) == "Shy Learner"
    blank.refresh_from_db()
    assert blank.display_name == "Shy Learner"


def test_ensure_display_name_keeps_existing_name():
    cohort = coursework_cohort()
    named = make_enrollment(cohort, "named@example.com", display_name="Ada Lovelace")

    assert ensure_display_name(named, generator=lambda enrollment: "Other") == "Ada Lovelace"


def test_ensure_enrollment_generates_display_name():
    cohort = coursework_cohort()
    user = User.objects.create_user(email="fresh@example.com")

    enrollment, created = ensure_enrollment(cohort, user)

    assert created is True
    assert enrollment.display_name
    again, created_again = ensure_enrollment(cohort, user)
    assert again.id == enrollment.id
    assert created_again is False


def test_set_enrollment_preference_updates_leaderboard_visibility(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_ENROLLMENT_PREFERENCES_UPDATED": lambda **event: seen.append(event["field"]),
    }
    cohort = coursework_cohort()
    enrollment = make_enrollment(cohort, "pref@example.com", total_score=3)
    enrollment.position_on_leaderboard = 1
    enrollment.save()

    enrollment, enabled, changed = set_enrollment_preference(
        cohort,
        enrollment.user,
        "display_on_leaderboard",
        "false",
    )

    assert enabled is False
    assert changed is True
    assert seen == ["display_on_leaderboard"]
    assert (
        get_leaderboard_data(
            cohort,
            current_student_leaderboard_enrollment(cohort, AnonymousUser()),
        )
        == []
    )


def test_set_learning_in_public_disabled_zeroes_scores_and_refreshes_leaderboard():
    cohort = coursework_cohort()
    hw = homework(cohort)
    project = cohort.projects.create(
        slug="proj1",
        title="Project 1",
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
        peer_review_due_date=timezone.now() + datetime.timedelta(days=2),
    )
    enrollment = make_enrollment(cohort, "quiet@example.com")
    homework_submission = Submission.objects.create(
        homework=hw,
        student=enrollment.user,
        enrollment=enrollment,
        questions_score=3,
        faq_score=1,
        learning_in_public_score=2,
        total_score=6,
    )
    project_submission = make_project_submission(
        project,
        enrollment,
        project_score=4,
        peer_review_score=3,
        project_learning_in_public_score=1,
        peer_review_learning_in_public_score=1,
        total_score=9,
    )

    set_learning_in_public_disabled(enrollment, disabled=True)

    homework_submission.refresh_from_db()
    project_submission.refresh_from_db()
    enrollment.refresh_from_db()
    assert homework_submission.learning_in_public_score == 0
    assert homework_submission.total_score == 4
    assert project_submission.project_learning_in_public_score == 0
    assert project_submission.peer_review_learning_in_public_score == 0
    assert project_submission.total_score == 7
    assert enrollment.total_score == 11

    set_learning_in_public_disabled(enrollment, disabled=False)
    enrollment.refresh_from_db()
    assert enrollment.disable_learning_in_public is False
    assert enrollment.total_score == 11


def test_score_homework_submissions_rejects_future_due_date():
    cohort = coursework_cohort()
    hw = homework(cohort)

    status, message = score_homework_submissions(hw.id)

    assert status is HomeworkScoringStatus.FAIL
    assert "due date" in message
    hw.refresh_from_db()
    assert hw.state != HomeworkState.SCORED.value


def test_score_homework_submissions_rejects_closed_and_already_scored():
    cohort = coursework_cohort()
    closed = homework(cohort, slug="closed", state=HomeworkState.CLOSED.value)
    scored = homework(cohort, slug="scored", state=HomeworkState.SCORED.value)

    status, message = score_homework_submissions(closed.id)
    assert status is HomeworkScoringStatus.FAIL
    assert "closed" in message

    status, message = score_homework_submissions(scored.id)
    assert status is HomeworkScoringStatus.FAIL
    assert "already scored" in message

    status, _message = score_homework_submissions(scored.id, force=True)
    assert status is HomeworkScoringStatus.OK


def test_score_homework_submissions_scores_updates_leaderboard_and_statistics():
    cohort = coursework_cohort()
    hw = homework(
        cohort,
        due_date=timezone.now() - datetime.timedelta(days=1),
    )
    q1 = question(
        hw,
        question_type=QuestionTypes.FREE_FORM.value,
        answer_type=AnswerTypes.EXACT_STRING.value,
        correct_answer="x",
        scores_for_correct_answer=2,
    )
    _, good = make_submission(cohort, hw, "good@example.com")
    good_answer = Answer.objects.create(submission=good, question=q1, answer_text="x")
    _, poor = make_submission(cohort, hw, "poor@example.com")
    poor_answer = Answer.objects.create(submission=poor, question=q1, answer_text="wrong")

    status, message = score_homework_submissions(hw.id)

    assert status is HomeworkScoringStatus.OK
    assert "scored" in message
    good.refresh_from_db()
    poor.refresh_from_db()
    good_answer.refresh_from_db()
    poor_answer.refresh_from_db()
    assert good.total_score == 2
    assert poor.total_score == 0
    assert good_answer.is_correct is True
    assert poor_answer.is_correct is False
    hw.refresh_from_db()
    assert hw.state == HomeworkState.SCORED.value
    cohort.refresh_from_db()
    assert cohort.first_homework_scored is True
    good_enrollment = Enrollment.objects.get(user__email="good@example.com")
    assert good_enrollment.total_score == 2
    assert good_enrollment.position_on_leaderboard == 1
    assert HomeworkStatistics.objects.filter(homework=hw).exists()
