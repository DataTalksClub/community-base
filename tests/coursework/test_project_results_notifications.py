from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from community_base.coursework.models import (
    Project,
    ProjectResultsNotification,
    ProjectResultsNotificationRecipient,
    ProjectState,
    ProjectSubmission,
)
from community_base.coursework.notifications import PROJECT_RESULTS_PURPOSE
from community_base.coursework.project_results_notifications import (
    ProjectResultsNotificationError,
    get_project_results_notification_status,
    preview_project_results_notifications,
    retry_failed_project_results_notifications,
    send_project_results_notifications,
)
from community_base.coursework.project_state import set_project_state
from community_base.curriculum.models import Cohort, Course, Enrollment
from community_base.jobs.models import JobIntent
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db

User = get_user_model()


def _make_course_cohort(slug="ml-course", cohort_slug="2026-fall", mode="cohort"):
    course = Course.objects.create(slug=slug, title=f"Course {slug}")
    cohort = Cohort.objects.create(
        course=course,
        slug=cohort_slug,
        title=f"Cohort {cohort_slug}",
        mode=mode,
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=30),
    )
    return course, cohort


def _make_project(cohort, slug="project-1", state=ProjectState.COMPLETED.value):
    now = timezone.now()
    is_self_paced = cohort.mode == "self_paced"
    return Project.objects.create(
        cohort=cohort,
        slug=slug,
        title=f"Project {slug}",
        state=state,
        submission_due_date=None if is_self_paced else now - timedelta(days=7),
        peer_review_due_date=None if is_self_paced else now - timedelta(days=1),
        commit_id_field=False,
    )


def _enroll_and_submit(
    project,
    email,
    *,
    submit=True,
    passed=False,
    project_score=0,
    volunteer_review_only=False,
):
    user = User.objects.create_user(
        email=email,
        password="pw",
    )
    enrollment = Enrollment.objects.create(user=user, cohort=project.cohort)
    submission = None
    if submit:
        submission = ProjectSubmission.objects.create(
            project=project,
            student=user,
            enrollment=enrollment,
            github_link=f"https://github.com/example/{user.pk}",
            passed=passed,
            project_score=project_score,
            total_score=project_score,
            volunteer_review_only=volunteer_review_only,
        )
    return user, enrollment, submission


def custom_results_url_builder(*, project, submission=None, user=None, **kwargs):
    del submission, user, kwargs
    return f"/courses/{project.cohort.course.slug}/projects/{project.slug}/reviews"


def test_scoping_pass_fail_independence_and_no_leakage():
    _course_a, cohort_a1 = _make_course_cohort("course-a", "cohort-1")
    _course_a2, cohort_a2 = _make_course_cohort("course-a-other", "cohort-1")
    cohort_a_second = Cohort.objects.create(
        course=cohort_a1.course,
        slug="cohort-2",
        title="Cohort 2",
        mode="cohort",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=30),
    )

    target_project = _make_project(cohort_a1, "attempt-1", ProjectState.COMPLETED.value)
    other_attempt = _make_project(cohort_a1, "attempt-2", ProjectState.COMPLETED.value)
    other_cohort_project = _make_project(cohort_a_second, "attempt-1", ProjectState.COMPLETED.value)
    other_course_project = _make_project(cohort_a2, "attempt-1", ProjectState.COMPLETED.value)

    passed_user, _, _ = _enroll_and_submit(
        target_project, "passed@example.com", passed=True, project_score=10
    )
    failed_user, _, _ = _enroll_and_submit(
        target_project, "failed@example.com", passed=False, project_score=0
    )
    _enroll_and_submit(target_project, "nonsubmitter@example.com", submit=False)
    _enroll_and_submit(target_project, "volunteer@example.com", volunteer_review_only=True)
    no_email_user, _, _ = _enroll_and_submit(target_project, "no-email@example.com")
    User.objects.filter(pk=no_email_user.pk).update(email="")
    _enroll_and_submit(other_attempt, "other-attempt@example.com")
    _enroll_and_submit(other_cohort_project, "other-cohort@example.com")
    _enroll_and_submit(other_course_project, "other-course@example.com")

    preview = preview_project_results_notifications(target_project)
    assert preview.eligible_count == 2
    assert preview.excluded_no_email_count == 1
    assert preview.can_send is True
    assert preview.already_sent is False
    assert EmailDelivery.objects.count() == 0
    assert ProjectResultsNotification.objects.count() == 0

    with override_settings(
        COMMUNITY_BASE={
            "SITE_URL": "https://example.test",
            "COURSEWORK_PROJECT_RESULTS_URL_BUILDER": custom_results_url_builder,
        }
    ):
        result = send_project_results_notifications(target_project, actor=passed_user)

    assert result.created is True
    assert result.already_sent is False
    assert result.status.eligible_count == 2
    assert result.status.enqueued_count == 2

    deliveries = list(EmailDelivery.objects.order_by("created_at", "id"))
    assert len(deliveries) == 2
    assert {d.recipient_email for d in deliveries} == {
        "passed@example.com",
        "failed@example.com",
    }
    for delivery in deliveries:
        assert delivery.purpose == PROJECT_RESULTS_PURPOSE
        assert delivery.category == "coursework"
        assert delivery.context_data["course_slug"] == "course-a"
        assert delivery.context_data["cohort_slug"] == "cohort-1"
        assert delivery.context_data["project_slug"] == "attempt-1"
        assert (
            delivery.context_data["results_url"] == "/courses/course-a/projects/attempt-1/reviews"
        )
        # Never leak grades, scores, or other recipients.
        serialized = str(delivery.context_data)
        assert "passed" not in serialized
        assert "project_score" not in serialized
        assert "total_score" not in serialized
        assert "failed@example.com" not in serialized
        assert "passed@example.com" not in serialized
    assert str(failed_user.pk) in {
        r.recipient_user_id for r in ProjectResultsNotificationRecipient.objects.all()
    }


def test_state_gates_closing_alone_and_no_historical_replay():
    _course, cohort = _make_course_cohort("gate-course", "c1")
    for state in (
        ProjectState.COLLECTING_SUBMISSIONS.value,
        ProjectState.PEER_REVIEWING.value,
        ProjectState.CLOSED.value,
    ):
        project = _make_project(cohort, f"proj-{state.lower()}", state=state)
        _enroll_and_submit(project, f"user-{state.lower()}@example.com")
        preview = preview_project_results_notifications(project)
        assert preview.can_send is False
        assert preview.blocked_code == "project_not_completed"
        with pytest.raises(ProjectResultsNotificationError) as exc_info:
            send_project_results_notifications(project)
        assert exc_info.value.code == "project_not_completed"

    # Closing reviews (PR -> CO) never sends mail on its own.
    pr_project = _make_project(cohort, "proj-close", state=ProjectState.PEER_REVIEWING.value)
    _enroll_and_submit(pr_project, "close-check@example.com")
    set_project_state(pr_project, ProjectState.COMPLETED)
    assert EmailDelivery.objects.count() == 0
    assert JobIntent.objects.count() == 0
    assert ProjectResultsNotification.objects.count() == 0

    # Existing completed project with submissions is never replayed by preview/status checks.
    existing_completed = _make_project(cohort, "existing-co", state=ProjectState.COMPLETED.value)
    _enroll_and_submit(existing_completed, "old-attempt@example.com")
    assert get_project_results_notification_status(existing_completed) is None
    preview_existing = preview_project_results_notifications(existing_completed)
    assert preview_existing.already_sent is False
    assert preview_existing.eligible_count == 1
    assert EmailDelivery.objects.count() == 0

    # Self-paced / pooled attempts are blocked.
    _sp_course, sp_cohort = _make_course_cohort("sp-course", "self-paced", mode="self_paced")
    sp_project = _make_project(sp_cohort, "sp-proj", state=ProjectState.COMPLETED.value)
    _enroll_and_submit(sp_project, "sp@example.com")
    sp_preview = preview_project_results_notifications(sp_project)
    assert sp_preview.can_send is False
    assert sp_preview.blocked_code == "self_paced_not_supported"


def test_audience_changes_reflected_before_send():
    _course, cohort = _make_course_cohort("aud-course", "c1")
    project = _make_project(cohort, "aud-proj", state=ProjectState.COMPLETED.value)
    _enroll_and_submit(project, "first@example.com")

    assert preview_project_results_notifications(project).eligible_count == 1

    # Add a second submitter and clear first user's email -> preview updates live.
    _enroll_and_submit(project, "second@example.com")
    User.objects.filter(email="first@example.com").update(email="")
    preview = preview_project_results_notifications(project)
    assert preview.eligible_count == 1
    assert preview.excluded_no_email_count == 1

    result = send_project_results_notifications(project)
    assert result.status.enqueued_count == 1
    assert list(EmailDelivery.objects.values_list("recipient_email", flat=True)) == [
        "second@example.com"
    ]


def test_double_click_concurrent_send_and_idempotent_retry():
    _course, cohort = _make_course_cohort("retry-course", "c1")
    project = _make_project(cohort, "retry-proj", state=ProjectState.COMPLETED.value)
    _enroll_and_submit(project, "one@example.com")
    _enroll_and_submit(project, "two@example.com")

    first = send_project_results_notifications(project)
    second = send_project_results_notifications(project)
    assert first.created is True
    assert second.created is False
    assert second.already_sent is True
    assert EmailDelivery.objects.count() == 2

    # Simulate concurrent IntegrityError race on a fresh project: row is committed by another
    # worker after our initial select_for_update check, so create() hits a real UNIQUE constraint.
    race_project = _make_project(cohort, "race-proj", state=ProjectState.COMPLETED.value)
    _enroll_and_submit(race_project, "race@example.com")
    send_project_results_notifications(race_project)
    from community_base.coursework.project_results_notifications import _project_scope

    _, _, _, _, _, race_hash = _project_scope(race_project)
    real_qs_filter = ProjectResultsNotification.objects.select_for_update

    class _MissedSelectForUpdate:
        def filter(self, **kwargs):
            if kwargs.get("scope_hash") == race_hash:
                return ProjectResultsNotification.objects.none()
            return real_qs_filter().filter(**kwargs)

    with patch.object(
        ProjectResultsNotification.objects,
        "select_for_update",
        return_value=_MissedSelectForUpdate(),
    ):
        race_result = send_project_results_notifications(race_project)
    assert race_result.created is False
    assert race_result.already_sent is True
    assert (
        EmailDelivery.objects.filter(
            project_results_recipients__notification__project_slug="race-proj"
        ).count()
        == 1
    )

    # Mark one delivery dead and leave the other delivered; retry only retries the dead one.
    deliveries = list(
        EmailDelivery.objects.filter(
            project_results_recipients__notification=first.notification
        ).order_by("id")
    )
    deliveries[0].state = EmailDelivery.State.DEAD
    deliveries[0].reason_code = "smtp_550"
    deliveries[0].save(update_fields=["state", "reason_code"])
    deliveries[1].state = EmailDelivery.State.DELIVERED
    deliveries[1].save(update_fields=["state"])

    retry_res = retry_failed_project_results_notifications(project)
    assert retry_res.retried_count == 1
    assert retry_res.status.dead_count == 0
    assert retry_res.status.pending_count == 1
    assert retry_res.status.accepted_or_delivered_count == 1

    # Second retry (double click) is a no-op.
    retry_again = retry_failed_project_results_notifications(project)
    assert retry_again.retried_count == 0


def test_studio_views_permissions_preview_send_and_retry(client):
    _course, cohort = _make_course_cohort("studio-course", "c1")
    project = _make_project(cohort, "studio-proj", state=ProjectState.COMPLETED.value)
    _enroll_and_submit(project, "learner@example.com")

    staff = User.objects.create_user(email="staff@example.com", password="pw", is_staff=True)
    member = User.objects.create_user(email="member@example.com", password="pw", is_staff=False)

    preview_url = reverse("coursework_studio_project_results_notifications", args=[project.pk])
    send_url = reverse("coursework_studio_project_results_notifications_send", args=[project.pk])
    retry_url = reverse("coursework_studio_project_results_notifications_retry", args=[project.pk])

    # Anonymous and non-staff cannot access preview, send, or retry.
    for url in (preview_url, send_url, retry_url):
        assert client.get(url).status_code in (302, 403)
        assert client.post(url).status_code in (302, 403)

    client.force_login(member)
    for url in (preview_url, send_url, retry_url):
        assert client.get(url).status_code in (302, 403)
        assert client.post(url).status_code in (302, 403)

    # Staff preview is read-only and shows exact eligible count.
    client.force_login(staff)
    resp = client.get(preview_url)
    assert resp.status_code == 200
    assert b"Eligible submitters: <strong>1</strong>" in resp.content
    assert EmailDelivery.objects.count() == 0

    # Send requires POST.
    assert client.get(send_url).status_code == 405
    assert client.get(retry_url).status_code == 405

    # Explicit POST send queues the email and exposes masked delivery state.
    send_resp = client.post(send_url, follow=True)
    assert send_resp.status_code == 200
    assert EmailDelivery.objects.count() == 1
    assert b"l***@example.com" in send_resp.content
    assert b"learner@example.com" not in send_resp.content

    # Mark dead and retry via Studio POST.
    delivery = EmailDelivery.objects.get()
    delivery.state = EmailDelivery.State.DEAD
    delivery.save(update_fields=["state"])
    retry_resp = client.post(retry_url, follow=True)
    assert retry_resp.status_code == 200
    assert EmailDelivery.objects.count() == 2
