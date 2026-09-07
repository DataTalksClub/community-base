import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    Answer,
    CourseRegistration,
    Homework,
    HomeworkStatistics,
    LeaderboardComplaint,
    Project,
    ProjectCriteriaAssignment,
    ProjectVote,
    Question,
    QuestionTypes,
    RegistrationCampaign,
    ReviewCriteria,
    ReviewCriteriaTypes,
    Submission,
    UserWrappedStatistics,
    WrappedStatistics,
)
from community_base.coursework.models import (
    Testimonial as MemberQuote,
)
from community_base.coursework.models import (
    TestimonialPlacement as QuotePlacement,
)
from community_base.curriculum.models import Course, Enrollment
from tests.curriculum.test_models import make_cohort

pytestmark = pytest.mark.django_db


def coursework_course():
    course, _created = Course.objects.get_or_create(
        slug="cw-course", defaults={"title": "Coursework Course", "status": "published"}
    )
    return course


def coursework_cohort(slug="cw", **cohort_values):
    cohort = make_cohort(coursework_course(), slug=slug, title="CW cohort", **cohort_values)
    cohort.project_passing_score = 5
    cohort.save()
    return cohort


def homework(cohort, **values):
    values.setdefault("slug", "hw1")
    values.setdefault("title", "Homework 1")
    values.setdefault("due_date", timezone.now() + datetime.timedelta(days=7))
    return Homework.objects.create(cohort=cohort, **values)


def question(hw, **values):
    values.setdefault("text", "What is 2+2?")
    values.setdefault("question_type", QuestionTypes.FREE_FORM.value)
    return Question.objects.create(homework=hw, **values)


def enrollment_for(cohort, email="learner@example.com"):
    user = User.objects.create_user(email=email)
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    return user, enrollment


def test_homework_state_helpers():
    cohort = coursework_cohort()
    hw = homework(cohort)
    assert hw.is_scored() is False
    hw.state = "SC"
    hw.save()
    assert hw.is_scored() is True
    assert str(hw) == "CW cohort - Homework 1"


def test_question_choice_answer_helpers_without_resolution():
    cohort = coursework_cohort()
    hw = homework(cohort)
    choice = question(
        hw,
        question_type=QuestionTypes.MULTIPLE_CHOICE.value,
        possible_answers="3\n4\n5",
        correct_answer="2",
    )
    free = question(hw, text="Free answer")

    assert choice.has_choice_answers() is True
    assert free.has_choice_answers() is False
    assert choice.get_possible_answers() == ["3", "4", "5"]


def test_question_source_option_ids_must_be_unique_strings():
    cohort = coursework_cohort()
    hw = homework(cohort)
    q = question(hw, source_option_ids=["a", "a"])

    with pytest.raises(ValidationError):
        q.full_clean()


def test_question_answer_envelope_must_be_object():
    cohort = coursework_cohort()
    hw = homework(cohort)
    q = question(hw, answer_envelope=["not", "an", "object"])

    with pytest.raises(ValidationError):
        q.full_clean()


def test_submission_scores_default_to_zero():
    cohort = coursework_cohort()
    hw = homework(cohort)
    user, enrollment = enrollment_for(cohort)
    submission = Submission.objects.create(homework=hw, student=user, enrollment=enrollment)

    assert submission.total_score == 0
    submission.total_score = 9
    submission.save()
    submission.refresh_from_db()
    assert submission.total_score == 9


def test_answer_str():
    cohort = coursework_cohort()
    hw = homework(cohort)
    user, enrollment = enrollment_for(cohort)
    submission = Submission.objects.create(homework=hw, student=user, enrollment=enrollment)
    q = question(hw)
    answer = Answer.objects.create(submission=submission, question=q, answer_text="4")

    assert "Answer id=" in str(answer)


def test_homework_statistics_display_fields():
    cohort = coursework_cohort()
    hw = homework(cohort)
    stats = HomeworkStatistics.objects.create(
        homework=hw,
        total_submissions=3,
        min_total_score=0,
        max_total_score=10,
    )

    assert stats.get_value("total_score", "max") == 10
    fields = stats.get_stat_fields()
    assert any(section[0] == "Total score" for section in fields)


def test_review_criteria_median_score_radio_vs_checkboxes():
    options = [
        {"criteria": "Poor", "score": 0},
        {"criteria": "Satisfactory", "score": 1},
        {"criteria": "Good", "score": 2},
        {"criteria": "Excellent", "score": 3},
    ]
    radio = ReviewCriteria.objects.create(
        description="Radio rubric",
        options=options,
        review_criteria_type=ReviewCriteriaTypes.RADIO_BUTTONS.value,
    )
    checkboxes = ReviewCriteria.objects.create(
        description="Checkbox rubric",
        options=options,
        review_criteria_type=ReviewCriteriaTypes.CHECKBOXES.value,
    )

    assert radio.median_score() == 2  # median of 0..3 -> 1.5 -> ceil
    assert checkboxes.median_score() == 3  # (0+1+2+3)/2 = 3


def test_review_criteria_options_validation():
    with pytest.raises(ValidationError):
        ReviewCriteria(description="Bad", options=[], review_criteria_type="RB").full_clean()
    with pytest.raises(ValidationError):
        ReviewCriteria(
            description="Bad",
            options=[{"criteria": "Only"}],
            review_criteria_type="RB",
        ).full_clean()


def test_project_criteria_assignment_rules():
    cohort = coursework_cohort()
    other = coursework_cohort(slug="cw-other")
    project = Project.objects.create(
        cohort=cohort,
        slug="final",
        title="Final project",
        submission_due_date=timezone.now(),
        peer_review_due_date=timezone.now(),
    )
    criteria = ReviewCriteria.objects.create(
        description="Quality",
        cohort=cohort,
        options=[{"criteria": "Bad", "score": 0}, {"criteria": "Good", "score": 2}],
        review_criteria_type=ReviewCriteriaTypes.RADIO_BUTTONS.value,
    )

    assignment = ProjectCriteriaAssignment(project=project, criteria=criteria, position=0)
    assignment.full_clean()
    assignment.save()

    assert list(project.criteria_for_project()) == [criteria]

    # Same criterion cannot be assigned to a project in another cohort.
    foreign_project = Project.objects.create(
        cohort=other,
        slug="final",
        title="Final project elsewhere",
        submission_due_date=timezone.now(),
        peer_review_due_date=timezone.now(),
    )
    foreign = ProjectCriteriaAssignment(project=foreign_project, criteria=criteria, position=0)
    with pytest.raises(ValidationError):
        foreign.full_clean()


def create_project_submission(project, enrollment, user):
    from community_base.coursework.models import ProjectSubmission

    return ProjectSubmission.objects.create(
        project=project,
        student=user,
        enrollment=enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
    )


def test_project_vote_is_unique_per_voter():
    cohort = coursework_cohort()
    project = Project.objects.create(
        cohort=cohort,
        slug="final",
        title="Final",
        submission_due_date=timezone.now(),
        peer_review_due_date=timezone.now(),
    )
    user, enrollment = enrollment_for(cohort)
    submission = create_project_submission(project, enrollment, user)

    ProjectVote.objects.create(submission=submission, voter=user)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectVote.objects.create(submission=submission, voter=user)


def test_project_points_to_pass_reads_cohort_setting():
    cohort = coursework_cohort()
    project = Project.objects.create(
        cohort=cohort,
        slug="final",
        title="Final",
        submission_due_date=timezone.now(),
        peer_review_due_date=timezone.now(),
    )

    assert project.points_to_pass == 5


def test_registration_campaign_count_fields_and_registration_default_cohort():
    cohort = coursework_cohort()
    campaign = RegistrationCampaign.objects.create(
        slug="de-2026",
        title="DE Zoomcamp 2026",
        current_cohort=cohort,
    )
    registration = CourseRegistration.objects.create(
        campaign=campaign,
        email="Learner@Example.com ",
        name="Learner",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.DATA_ENGINEER,
    )

    assert registration.cohort_id == cohort.id
    assert registration.email_normalized == "learner@example.com"

    with pytest.raises(IntegrityError), transaction.atomic():
        CourseRegistration.objects.create(
            campaign=campaign,
            email="learner@example.com",
            name="Duplicate",
            country="DE",
            region="EU",
            role=CourseRegistration.Role.OTHER,
        )


def test_leaderboard_complaint_flow():
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort)
    staff = User.objects.create_user(email="staff@example.com", is_staff=True)
    complaint = LeaderboardComplaint.objects.create(
        enrollment=enrollment,
        reporter=staff,
        issue_type=LeaderboardComplaint.IssueType.HOMEWORK,
        description="Score missing",
    )

    assert "Incorrect homework" in str(complaint)
    complaint.resolved = True
    complaint.resolved_at = timezone.now()
    complaint.resolved_by = staff
    complaint.save()
    assert complaint.resolved is True


def test_testimonial_placement_scope():
    course = coursework_course()

    homepage = MemberQuote(placement=QuotePlacement.HOMEPAGE, name="A", quote="q")
    homepage.full_clean()
    homepage.save()

    course_quote = MemberQuote(placement=QuotePlacement.COURSE, course=course, name="B", quote="q")
    course_quote.full_clean()
    course_quote.save()

    bad = MemberQuote(placement=QuotePlacement.HOMEPAGE, course=course, name="C", quote="q")
    with pytest.raises(ValidationError):
        bad.full_clean()

    with pytest.raises(IntegrityError), transaction.atomic():
        MemberQuote(placement=QuotePlacement.HOMEPAGE, course=course, name="D", quote="q").save()


def test_wrapped_statistics_models():
    wrapped = WrappedStatistics.objects.create(year=2025, total_participants=100)
    learner = User.objects.create_user(email="wrapped@example.com")
    user_stats = UserWrappedStatistics.objects.create(
        wrapped=wrapped,
        user=learner,
        display_name="Learner",
        rank=1,
    )

    assert str(wrapped) == "Wrapped 2025 (Hidden)"
    assert user_stats.rank == 1

    with pytest.raises(IntegrityError), transaction.atomic():
        UserWrappedStatistics.objects.create(wrapped=wrapped, user=learner)


def test_coursework_tables_are_new_labels():
    from django.apps import apps

    config = apps.get_app_config("cb_coursework")
    assert config.label == "cb_coursework"
    assert Homework._meta.db_table.startswith("cb_coursework_")
