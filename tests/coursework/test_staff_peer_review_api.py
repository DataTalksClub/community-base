"""Tests for staff peer-review API endpoints and non-blocking review_assigned emails."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.api.models import APIKey
from community_base.coursework import notifications
from community_base.coursework.models import (
    PeerReview,
    PeerReviewState,
    Project,
    ProjectState,
    ProjectSubmission,
)
from community_base.curriculum.models import Cohort, Course, Enrollment
from community_base.mail.models import EmailDelivery
from community_base.mail.service import MailError


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def coursework_keys(db):
    staff = User.objects.create_user(email="cw-staff@example.com", is_staff=True)
    _, read_key = APIKey.create_for_user(
        user=staff, name="cw-read", scopes=["coursework.read"], kind=APIKey.Kind.STAFF
    )
    _, write_key = APIKey.create_for_user(
        user=staff, name="cw-write", scopes=["coursework.write"], kind=APIKey.Kind.STAFF
    )
    return read_key, write_key


@pytest.fixture
def dated_course_with_submissions(db):
    now = timezone.now()
    course = Course.objects.create(slug="ai-buildcamp", title="AI Buildcamp")
    cohort = Cohort.objects.create(
        course=course,
        slug="4",
        title="Cohort 4",
        mode="cohort",
        start_date=(now - timedelta(days=20)).date(),
        end_date=(now + timedelta(days=10)).date(),
    )
    project = Project.objects.create(
        cohort=cohort,
        slug="attempt-1",
        title="Project Attempt 1",
        number_of_peers_to_evaluate=2,
        submission_due_date=now - timedelta(hours=2),
        peer_review_due_date=now + timedelta(days=7),
        state=ProjectState.COLLECTING_SUBMISSIONS.value,
    )
    students = []
    for idx in range(4):
        user = User.objects.create_user(email=f"student{idx}@example.com")
        enrollment = Enrollment.objects.create(user=user, cohort=cohort)
        ProjectSubmission.objects.create(
            project=project,
            student=user,
            enrollment=enrollment,
            github_link=f"https://github.com/example/proj-{idx}",
            commit_id="abcdef1",
        )
        students.append(user)
    return course, cohort, project, students


@pytest.mark.django_db
def test_peer_reviews_api_requires_scopes(client, coursework_keys, dated_course_with_submissions):
    read_key, write_key = coursework_keys
    assert client.get("/api/v1/courses/ai-buildcamp/peer-reviews").status_code == 401
    assert (
        client.get(
            "/api/v1/courses/ai-buildcamp/peer-reviews", headers=_bearer(write_key)
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/courses/ai-buildcamp/peer-reviews/assignments", headers=_bearer(read_key)
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_peer_reviews_read_and_assign_are_idempotent_with_emails(
    client, coursework_keys, dated_course_with_submissions
):
    read_key, write_key = coursework_keys
    course, _cohort, project, students = dated_course_with_submissions

    resp_before = client.get(
        "/api/v1/courses/ai-buildcamp/peer-reviews?cohort=4&project=attempt-1",
        headers=_bearer(read_key),
    )
    assert resp_before.status_code == 200
    before = resp_before.json()
    assert before["course_id"] == course.pk
    assert before["projects"][0]["state"] == "CS"
    assert before["projects"][0]["submissions_count"] == 4
    assert before["projects"][0]["assignments_count"] == 0

    assign_1 = client.post(
        "/api/v1/courses/ai-buildcamp/peer-reviews/assignments",
        {"cohort": "4", "project": "attempt-1"},
        content_type="application/json",
        headers=_bearer(write_key),
    )
    assert assign_1.status_code == 200
    body_1 = assign_1.json()
    assert body_1["course_id"] == course.pk
    assert body_1["batched"] == 4
    assert body_1["reviews_assigned"] == 8
    assert body_1["projects"][0]["state"] == "PR"
    assert body_1["projects"][0]["assignments_count"] == 8
    assert (
        EmailDelivery.objects.filter(
            purpose="coursework.review_assigned", recipient_user__in=students
        ).count()
        == 4
    )

    review = PeerReview.objects.filter(submission_under_evaluation__project=project).first()
    review.state = PeerReviewState.SUBMITTED.value
    review.save(update_fields=["state"])

    resp_after = client.get(
        "/api/v1/courses/ai-buildcamp/peer-reviews?cohort=4&project=attempt-1",
        headers=_bearer(read_key),
    )
    proj_after = resp_after.json()["projects"][0]
    assert proj_after["completed_reviews_count"] == 1
    assert proj_after["pending_reviews_count"] == 7

    assign_2 = client.post(
        "/api/v1/courses/ai-buildcamp/peer-reviews/assignments",
        {"cohort": "4", "project": "attempt-1"},
        content_type="application/json",
        headers=_bearer(write_key),
    )
    assert assign_2.status_code == 200
    body_2 = assign_2.json()
    assert body_2["batched"] == 0
    assert body_2["reviews_assigned"] == 0
    assert (
        EmailDelivery.objects.filter(
            purpose="coursework.review_assigned", recipient_user__in=students
        ).count()
        == 4
    )


@pytest.mark.django_db
def test_peer_reviews_api_404_errors(client, coursework_keys, dated_course_with_submissions):
    read_key, write_key = coursework_keys
    assert (
        client.get("/api/v1/courses/unknown/peer-reviews", headers=_bearer(read_key)).status_code
        == 404
    )
    assert (
        client.get(
            "/api/v1/courses/ai-buildcamp/peer-reviews?cohort=999", headers=_bearer(read_key)
        ).json()["error"]["code"]
        == "unknown_cohort"
    )
    assert (
        client.post(
            "/api/v1/courses/ai-buildcamp/peer-reviews/assignments",
            {"project": "nope"},
            content_type="application/json",
            headers=_bearer(write_key),
        ).json()["error"]["code"]
        == "unknown_project"
    )


@pytest.mark.django_db
def test_review_assigned_notification_failure_is_non_blocking(dated_course_with_submissions):
    _course, _cohort, project, students = dated_course_with_submissions
    subs = list(ProjectSubmission.objects.filter(project=project).order_by("id"))
    reviews = [
        PeerReview.objects.create(
            submission_under_evaluation=subs[1], reviewer=subs[0], note_to_peer=""
        ),
        PeerReview.objects.create(
            submission_under_evaluation=subs[0], reviewer=subs[1], note_to_peer=""
        ),
    ]
    failing_email = subs[0].student.email

    def fail_first(purpose, to, context, idempotency_key, **kwargs):
        if to == failing_email:
            raise MailError("simulated failure")
        return EmailDelivery.objects.create(
            purpose=purpose,
            recipient_user=kwargs.get("user"),
            recipient_email=to,
            idempotency_key=idempotency_key,
        )

    with patch("community_base.coursework.notifications.send", side_effect=fail_first):
        sent = notifications.send_review_assigned_notifications(reviews)

    assert sent == 1
    assert EmailDelivery.objects.filter(purpose="coursework.review_assigned").count() == 1
