"""Coursework Studio surfaces (plan issue C5.2e): homework rescoring, peer review
administration, leaderboard recompute, complaint resolution, certificates,
campaigns and wrapped statistics.

Mirrors the donor intent of `dtc-website/studio_courses/tests/` for the flows
that have a package service behind them.
"""

import datetime

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.leaderboard import file_leaderboard_complaint
from community_base.coursework.models import (
    Answer,
    AnswerTypes,
    HomeworkState,
    LeaderboardComplaint,
    PeerReview,
    ProjectCriteriaAssignment,
    ProjectState,
    QuestionTypes,
    ReviewCriteria,
    ReviewCriteriaTypes,
    Submission,
    UserWrappedStatistics,
    WrappedStatistics,
)
from community_base.coursework.review import (
    add_volunteer_peer_review,
    assign_peer_reviews_for_project,
)
from community_base.coursework.scoring import score_homework_submissions
from community_base.curriculum.models import Certificate
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_models import homework as make_homework
from tests.coursework.test_models import question as make_question
from tests.coursework.test_peer_review import (
    close_review_window,
    make_criteria,
    make_submissions,
    submit_all_reviews,
)
from tests.coursework.test_projects import make_project
from tests.coursework.test_registration import make_campaign, make_registration

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client, django_user_model):
    user = django_user_model.objects.create_user(email="studio-admin@example.com", is_staff=True)
    client.force_login(user)
    return user


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def homework_form_data(**overrides):
    data = {
        "title": "Studio homework",
        "slug": "studio-hw",
        "due_date": (timezone.now() + datetime.timedelta(days=3)).strftime("%Y-%m-%d %H:%M"),
        "state": HomeworkState.OPEN.value,
        "learning_in_public_cap": 3,
    }
    data.update(overrides)
    return data


def question_form_data(**overrides):
    data = {
        "text": "What is 3+3?",
        "question_type": QuestionTypes.FREE_FORM.value,
        "scores_for_correct_answer": "2",
    }
    data.update(overrides)
    return data


def past_due_homework(cohort, **values):
    values.setdefault("due_date", timezone.now() - datetime.timedelta(hours=1))
    return make_homework(cohort, **values)


def assigning_project(cohort):
    return make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )


def review_criteria():
    return ReviewCriteria.objects.create(
        description="Quality",
        options=[{"criteria": "Poor", "score": 0}, {"criteria": "Good", "score": 6}],
        review_criteria_type=ReviewCriteriaTypes.RADIO_BUTTONS.value,
    )


# --- staff gate ---------------------------------------------------------------


def test_studio_requires_staff(client, django_user_model):
    coursework_cohort()
    list_url = reverse("coursework_studio_homework_list")

    anonymous = client.get(list_url)
    assert anonymous.status_code == 302
    assert anonymous.url.startswith("/accounts/login/")

    member = django_user_model.objects.create_user(email="member@example.com")
    client.force_login(member)
    assert client.get(list_url).status_code == 403

    staff_user = django_user_model.objects.create_user(email="staff-2@example.com", is_staff=True)
    client.force_login(staff_user)
    assert client.get(list_url).status_code == 200


def test_anonymous_post_action_is_redirected_to_login(client):
    cohort = coursework_cohort()
    hw = make_homework(cohort)

    response = client.post(reverse("coursework_studio_homework_rescore", args=[hw.pk]))

    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")


# --- homework and questions ---------------------------------------------------


def test_homework_list_filters_by_cohort(client, staff):
    cohort = coursework_cohort()
    other = coursework_cohort(slug="cw-list-other")
    make_homework(cohort, slug="hw-a")
    make_homework(other, slug="hw-b")

    all_rows = client.get(reverse("coursework_studio_homework_list"))
    filtered = client.get(reverse("coursework_studio_homework_list"), {"cohort": cohort.pk})

    assert all_rows.status_code == 200
    assert filtered.status_code == 200
    assert b"hw-a" in all_rows.content
    assert b"hw-b" in all_rows.content
    assert b"hw-b" not in filtered.content


def test_homework_create_sets_cohort_and_redirects_to_detail(client, staff):
    cohort = coursework_cohort()
    create_url = reverse("coursework_studio_homework_create", args=[cohort.pk])

    assert client.get(create_url).status_code == 200

    response = client.post(create_url, homework_form_data())

    assert response.status_code == 302
    hw = cohort.homeworks.get(slug="studio-hw")
    assert response.url == reverse("coursework_studio_homework_detail", args=[hw.pk])
    assert hw.title == "Studio homework"
    assert hw.cohort == cohort


def test_homework_edit_persists_and_redirects_to_detail(client, staff):
    cohort = coursework_cohort()
    hw = make_homework(cohort)

    response = client.post(
        reverse("coursework_studio_homework_edit", args=[hw.pk]),
        homework_form_data(title="Renamed homework"),
    )

    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_homework_detail", args=[hw.pk])
    hw.refresh_from_db()
    assert hw.title == "Renamed homework"


def test_question_create_and_edit_redirect_back_and_persist(client, staff):
    cohort = coursework_cohort()
    hw = make_homework(cohort)

    response = client.post(
        reverse("coursework_studio_question_create", args=[hw.pk]), question_form_data()
    )

    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_homework_detail", args=[hw.pk])
    question = hw.questions.get(text="What is 3+3?")
    assert question.scores_for_correct_answer == 2

    response = client.post(
        reverse("coursework_studio_question_edit", args=[question.pk]),
        question_form_data(text="Updated prompt", scores_for_correct_answer="5"),
    )

    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_homework_detail", args=[hw.pk])
    question.refresh_from_db()
    assert question.text == "Updated prompt"
    assert question.scores_for_correct_answer == 5


def test_question_delete_removes_question_and_rejects_get(client, staff):
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    question = make_question(hw)
    delete_url = reverse("coursework_studio_question_delete", args=[question.pk])

    response = client.get(delete_url)

    assert response.status_code == 405

    response = client.post(delete_url)

    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_homework_detail", args=[hw.pk])
    assert not hw.questions.filter(pk=question.pk).exists()


def test_homework_rescore_scores_submissions_and_reranks_leaderboard(client, staff):
    cohort = coursework_cohort()
    hw = past_due_homework(cohort)
    question = make_question(hw, answer_type=AnswerTypes.ANY.value)
    user, enrollment = enrollment_for(cohort, email="rescored@example.com")
    submission = Submission.objects.create(homework=hw, student=user, enrollment=enrollment)
    Answer.objects.create(submission=submission, question=question, answer_text="my answer")

    response = client.post(
        reverse("coursework_studio_homework_rescore", args=[hw.pk]), follow=True
    )

    assert response.status_code == 200
    hw.refresh_from_db()
    assert hw.state == HomeworkState.SCORED.value
    submission.refresh_from_db()
    assert submission.total_score == 1
    enrollment.refresh_from_db()
    assert enrollment.total_score == 1
    assert enrollment.position_on_leaderboard == 1


def test_homework_rescore_without_force_warns_and_force_rescores(client, staff):
    cohort = coursework_cohort()
    hw = past_due_homework(cohort)
    user, enrollment = enrollment_for(cohort, email="forced@example.com")
    Submission.objects.create(homework=hw, student=user, enrollment=enrollment, total_score=2)
    status, _message = score_homework_submissions(hw.pk)
    assert status.value == "OK"
    rescore_url = reverse("coursework_studio_homework_rescore", args=[hw.pk])

    response = client.post(rescore_url, follow=True)

    assert any("already scored" in message for message in messages_of(response))
    hw.refresh_from_db()
    assert hw.state == HomeworkState.SCORED.value

    response = client.post(rescore_url, {"force": "1"}, follow=True)

    assert any(
        "is scored" in message and "already scored" not in message
        for message in messages_of(response)
    )
    hw.refresh_from_db()
    assert hw.state == HomeworkState.SCORED.value
    enrollment.refresh_from_db()
    assert enrollment.total_score == 2


# --- projects and peer review administration ----------------------------------


def test_project_assign_reviews_creates_required_reviews(client, staff):
    cohort = coursework_cohort()
    project = assigning_project(cohort)
    make_submissions(project, cohort, 3)

    response = client.post(
        reverse("coursework_studio_project_assign_reviews", args=[project.pk]), follow=True
    )

    assert response.status_code == 200
    project.refresh_from_db()
    assert project.state == ProjectState.PEER_REVIEWING.value
    reviews = PeerReview.objects.filter(submission_under_evaluation__project=project)
    assert reviews.count() == 6
    assert all(review.optional is False for review in reviews)


def test_project_score_completes_project_and_passes_submissions(client, staff):
    cohort = coursework_cohort()
    project = assigning_project(cohort)
    make_criteria(project)
    submissions = make_submissions(project, cohort, 3)
    status, _message = assign_peer_reviews_for_project(project)
    assert status.value == "OK"
    submit_all_reviews(project)
    close_review_window(project)

    response = client.post(
        reverse("coursework_studio_project_score", args=[project.pk]), follow=True
    )

    assert response.status_code == 200
    project.refresh_from_db()
    assert project.state == ProjectState.COMPLETED.value
    for submission in submissions:
        submission.refresh_from_db()
        assert submission.project_score == 6
        assert submission.passed is True


def test_volunteer_review_add_creates_one_optional_review(client, staff):
    cohort = coursework_cohort()
    project = assigning_project(cohort)
    submissions = make_submissions(project, cohort, 3)
    volunteer = User.objects.create_user(email="studio-volunteer@example.com")
    add_url = reverse("coursework_studio_volunteer_review_add", args=[project.pk])

    response = client.post(
        add_url,
        {"email": volunteer.email, "submission_id": submissions[0].pk},
        follow=True,
    )

    assert response.status_code == 200
    reviews = PeerReview.objects.filter(reviewer__student=volunteer, optional=True)
    assert reviews.count() == 1
    assert reviews.get().submission_under_evaluation == submissions[0]

    client.post(add_url, {"email": volunteer.email, "submission_id": submissions[0].pk}, follow=True)

    assert reviews.count() == 1


def test_volunteer_review_remove_deletes_optional_review(client, staff):
    cohort = coursework_cohort()
    project = assigning_project(cohort)
    submissions = make_submissions(project, cohort, 3)
    volunteer = User.objects.create_user(email="removable-volunteer@example.com")
    review, _created = add_volunteer_peer_review(project, volunteer, submissions[0])

    response = client.post(
        reverse("coursework_studio_volunteer_review_remove", args=[project.pk, review.pk]),
        {"email": volunteer.email},
        follow=True,
    )

    assert response.status_code == 200
    assert not PeerReview.objects.filter(pk=review.pk).exists()


def test_criteria_add_persists_assignment_and_invalid_form_shows_error(client, staff):
    cohort = coursework_cohort()
    project = make_project(cohort)
    criteria = review_criteria()
    add_url = reverse("coursework_studio_criteria_add", args=[project.pk])

    response = client.post(add_url, {"criteria": criteria.pk, "position": "0"}, follow=True)

    assert response.status_code == 200
    assert ProjectCriteriaAssignment.objects.filter(project=project, criteria=criteria).exists()

    response = client.post(add_url, {"criteria": "", "position": ""}, follow=True)

    assert response.status_code == 200
    assert any("criterion" in message.lower() for message in messages_of(response))
    assert ProjectCriteriaAssignment.objects.filter(project=project).count() == 1


def test_criteria_remove_deletes_assignment(client, staff):
    cohort = coursework_cohort()
    project = make_project(cohort)
    make_criteria(project)
    assignment = project.criteria_assignments.get()

    response = client.post(
        reverse("coursework_studio_criteria_remove", args=[project.pk, assignment.pk])
    )

    assert response.status_code == 302
    assert not ProjectCriteriaAssignment.objects.filter(pk=assignment.pk).exists()


# --- leaderboard, complaints, certificates, campaigns, wrapped ----------------


def test_leaderboard_recompute_ranks_enrollments_and_page_lists_rows(client, staff):
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    first_user, first = enrollment_for(cohort, email="leader1@example.com")
    Submission.objects.create(homework=hw, student=first_user, enrollment=first, total_score=5)
    second_user, second = enrollment_for(cohort, email="leader2@example.com")
    Submission.objects.create(homework=hw, student=second_user, enrollment=second, total_score=3)

    response = client.post(
        reverse("coursework_studio_leaderboard_recompute", args=[cohort.pk]), follow=True
    )

    assert response.status_code == 200
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.total_score == 5
    assert first.position_on_leaderboard == 1
    assert second.total_score == 3
    assert second.position_on_leaderboard == 2
    assert b"leader1@example.com" in response.content
    assert b"leader2@example.com" in response.content


def test_complaints_page_lists_open_complaint(client, staff):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="complained@example.com")
    file_leaderboard_complaint(
        enrollment,
        user,
        issue_type=LeaderboardComplaint.IssueType.HOMEWORK,
        description="Homework 1 was scored wrong.",
    )

    response = client.get(reverse("coursework_studio_complaints"))

    assert response.status_code == 200
    assert b"Homework 1 was scored wrong." in response.content


def test_complaint_resolve_sets_resolver_and_keeps_totals(client, staff):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="resolved@example.com")
    enrollment.total_score = 10
    enrollment.save(update_fields=["total_score"])
    complaint = file_leaderboard_complaint(
        enrollment,
        user,
        issue_type=LeaderboardComplaint.IssueType.PROJECT,
        description="Project was scored wrong.",
    )

    response = client.post(
        reverse("coursework_studio_complaint_resolve", args=[complaint.pk]), follow=True
    )

    assert response.status_code == 200
    complaint.refresh_from_db()
    assert complaint.resolved is True
    assert complaint.resolved_at is not None
    assert complaint.resolved_by == staff
    enrollment.refresh_from_db()
    assert enrollment.total_score == 10


def test_complaint_create_files_complaint_for_enrollment(client, staff):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="reported@example.com")

    response = client.post(
        reverse("coursework_studio_complaint_create", args=[enrollment.pk]),
        {"issue_type": LeaderboardComplaint.IssueType.HOMEWORK.value, "description": "Recheck"},
        follow=True,
    )

    assert response.status_code == 200
    complaint = LeaderboardComplaint.objects.get(enrollment=enrollment)
    assert complaint.issue_type == LeaderboardComplaint.IssueType.HOMEWORK.value
    assert complaint.reporter == staff
    expected_redirect = reverse("coursework_studio_cohort_leaderboard", args=[cohort.pk])
    assert response.redirect_chain[-1][0] == expected_redirect


def test_certificate_issue_creates_row_then_updates_without_duplicates(client, staff):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="certified@example.com")
    issue_url = reverse("coursework_studio_certificate_issue", args=[cohort.pk, enrollment.pk])

    response = client.post(issue_url, {"url": "https://example.com/certificates/abc"}, follow=True)

    assert response.status_code == 200
    assert any("issued" in message for message in messages_of(response))
    certificate = Certificate.objects.get(enrollment=enrollment)
    assert certificate.url == "https://example.com/certificates/abc"
    enrollment.refresh_from_db()
    assert enrollment.certificate_url == "https://example.com/certificates/abc"

    client.post(issue_url, {"url": "https://example.com/certificates/abc"}, follow=True)

    assert Certificate.objects.filter(enrollment=enrollment).count() == 1


def test_campaigns_page_shows_baseline_plus_native_count(client, staff):
    cohort = coursework_cohort()
    campaign = make_campaign(
        slug="studio-de",
        title="Studio campaign",
        current_cohort=cohort,
        registration_baseline_cohort=cohort,
        registration_baseline_count=120,
    )
    make_registration(campaign, "registered@example.com", cohort=cohort)

    response = client.get(reverse("coursework_studio_campaigns"))

    assert response.status_code == 200
    assert b"Studio campaign" in response.content
    assert b"121" in response.content


def test_wrapped_page_renders(client, staff):
    response = client.get(reverse("coursework_studio_wrapped"))

    assert response.status_code == 200


def test_wrapped_recalculate_builds_year_statistics(client, staff):
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort, email="wrapped-2026@example.com")
    Submission.objects.create(
        homework=make_homework(cohort),
        student=user,
        enrollment=enrollment,
        submitted_at=timezone.now(),
    )

    response = client.post(
        reverse("coursework_studio_wrapped_recalculate"), {"year": "2026"}, follow=True
    )

    assert response.status_code == 200
    stats = WrappedStatistics.objects.get(year=2026)
    assert stats.total_participants == 1
    assert UserWrappedStatistics.objects.filter(wrapped=stats, user=user).exists()


def test_wrapped_recalculate_rejects_invalid_year(client, staff):
    response = client.post(
        reverse("coursework_studio_wrapped_recalculate"), {"year": "soon"}, follow=True
    )

    assert response.status_code == 200
    assert any("valid year" in message for message in messages_of(response))
    assert WrappedStatistics.objects.count() == 0
