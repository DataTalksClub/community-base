import datetime
import json

import pytest
from django.contrib.messages import get_messages
from django.urls import include, path, reverse
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.certificates import issue_certificate
from community_base.coursework.models import (
    LeaderboardComplaint,
    PeerReview,
    ProjectState,
    ProjectSubmission,
    Submission,
)
from community_base.coursework.review import assign_peer_reviews_for_project
from community_base.curriculum.models import Certificate, Enrollment
from tests.coursework.test_models import (
    coursework_cohort,
    enrollment_for,
)
from tests.coursework.test_models import (
    homework as make_homework,
)
from tests.coursework.test_models import (
    question as make_question,
)
from tests.coursework.test_peer_review import make_criteria, make_submissions
from tests.coursework.test_projects import make_project

urlpatterns = [path("courses/", include("community_base.coursework.urls"))]

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def coursework_urlconf(settings):
    settings.ROOT_URLCONF = __name__


def homework_url(course_slug="cw-course", cohort="cw", slug="hw1"):
    return reverse("coursework_homework", args=[course_slug, cohort, slug])


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def test_anonymous_homework_get_renders_disabled_page(client):
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    make_question(hw)
    url = homework_url()

    response = client.get(url)

    assert response.status_code == 200
    assert response.context["disabled"] is True
    assert response.context["is_authenticated"] is False
    assert response.context["accepting_submissions"] is True
    assert response.context["homework"] == hw
    assert Enrollment.objects.count() == 0

    posted = client.post(url, {"answer_1": "x"})
    assert posted.status_code == 200
    assert posted.context["disabled"] is True
    assert Enrollment.objects.count() == 0
    assert Submission.objects.count() == 0


def test_homework_post_creates_enrollment_submission_and_fires_hook(settings, client):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_HOMEWORK_SUBMITTED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    hw = make_homework(cohort)
    first = make_question(hw, answer_type="ANY")
    second = make_question(hw, text="Introduce yourself", answer_type="ANY")
    user = User.objects.create_user(email="hw-poster@example.com")
    client.force_login(user)

    response = client.post(
        homework_url(),
        {f"answer_{first.id}": "4", f"answer_{second.id}": "hello"},
    )

    assert response.status_code == 302
    assert response.url == homework_url()
    enrollment = Enrollment.objects.get(cohort=cohort, user=user)
    submission = Submission.objects.get(homework=hw, student=user)
    assert submission.enrollment == enrollment
    assert submission.answers.count() == 2
    assert submission.total_score == 2
    assert seen == [{"submission": submission}]


def test_closed_homework_post_fires_rejected_and_saves_nothing(settings, client):
    rejected = []
    submitted = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_HOMEWORK_SUBMISSION_REJECTED": lambda **event: rejected.append(event),
        "COURSEWORK_HOMEWORK_SUBMITTED": lambda **event: submitted.append(event),
    }
    cohort = coursework_cohort()
    hw = make_homework(cohort, state="CL")
    question = make_question(hw, answer_type="ANY")
    _user, enrollment = enrollment_for(cohort, email="closed-view@example.com")
    client.force_login(enrollment.user)

    response = client.post(homework_url(), {f"answer_{question.id}": "4"}, follow=True)

    assert response.status_code == 200
    assert any("closed" in message for message in messages_of(response))
    assert rejected == [{"homework": hw, "enrollment": enrollment, "reason": "closed"}]
    assert submitted == []
    assert Submission.objects.count() == 0
    assert Enrollment.objects.count() == 1


def test_project_submit_and_delete_through_the_view(client):
    cohort = coursework_cohort()
    project = make_project(cohort)
    user = User.objects.create_user(email="project-poster@example.com")
    client.force_login(user)
    url = reverse("coursework_project", args=["cw-course", "cw", project.slug])

    response = client.post(
        url,
        {"github_link": "https://github.com/example/repo", "commit_id": "a" * 40},
    )

    assert response.status_code == 302
    submission = ProjectSubmission.objects.get(project=project, student=user)
    assert submission.volunteer_review_only is False

    deleted = client.post(url, {"action": "delete"})

    assert deleted.status_code == 302
    assert ProjectSubmission.objects.count() == 0


def test_project_post_on_closed_project_rerenders_with_error(client):
    cohort = coursework_cohort()
    project = make_project(cohort)
    project.state = ProjectState.PEER_REVIEWING.value
    project.save()
    user = User.objects.create_user(email="closed-project@example.com")
    client.force_login(user)
    url = reverse("coursework_project", args=["cw-course", "cw", project.slug])

    response = client.post(
        url, {"github_link": "https://github.com/example/repo", "commit_id": "a" * 40}
    )

    assert response.status_code == 200
    assert response.context["disabled"] is True
    assert any("closed" in message for message in messages_of(response))
    assert ProjectSubmission.objects.count() == 0


def reviewed_project():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_criteria(project)
    make_submissions(project, cohort, 3)
    status, _message = assign_peer_reviews_for_project(project)
    assert status.value == "OK"
    return cohort, project


def test_peer_review_submit_happy_path(client):
    _cohort, project = reviewed_project()
    review = PeerReview.objects.order_by("id").first()
    criteria = project.criteria_for_project().first()
    client.force_login(review.reviewer.student)
    url = reverse(
        "coursework_projects_eval_submit",
        args=["cw-course", "cw", project.slug, review.id],
    )

    response = client.post(url, {f"criteria_{criteria.id}": "2"})

    expected_eval_url = reverse("coursework_projects_eval", args=["cw-course", "cw", project.slug])
    assert response.status_code == 302
    assert response.url == expected_eval_url
    review.refresh_from_db()
    assert review.state == "SU"
    assert review.criteria_responses.get().answer == "2"


def test_peer_review_submit_rejects_non_owner(client):
    _cohort, project = reviewed_project()
    review = PeerReview.objects.order_by("id").first()
    criteria = project.criteria_for_project().first()
    intruder = User.objects.create_user(email="intruder@example.com")
    client.force_login(intruder)
    url = reverse(
        "coursework_projects_eval_submit",
        args=["cw-course", "cw", project.slug, review.id],
    )

    response = client.post(url, {f"criteria_{criteria.id}": "2"}, follow=True)

    assert response.status_code == 200
    assert any("not yours" in message for message in messages_of(response))
    review.refresh_from_db()
    assert review.state == "TR"
    assert review.criteria_responses.count() == 0


def test_leaderboard_page_lists_ranked_and_hides_hidden_enrollment(client):
    cohort = coursework_cohort()
    visible_user, visible_enrollment = enrollment_for(cohort, email="visible@example.com")
    _hidden_user, hidden_enrollment = enrollment_for(cohort, email="hidden@example.com")
    hidden_enrollment.display_on_leaderboard = False
    hidden_enrollment.save()
    Enrollment.objects.filter(id=visible_enrollment.id).update(display_name="Visible Learner")

    response = client.get(reverse("coursework_leaderboard", args=["cw-course", "cw"]))

    assert response.status_code == 200
    listed_ids = [row["id"] for row in response.context["enrollments"]]
    assert visible_enrollment.id in listed_ids
    assert hidden_enrollment.id not in listed_ids
    assert response.context["total_enrollments"] == 1
    assert response.context["current_student_enrollment_id"] is None


def test_leaderboard_complaint_files_a_complaint(client):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="complained@example.com")
    reporter = User.objects.create_user(email="reporter@example.com")
    client.force_login(reporter)
    url = reverse("coursework_leaderboard_complaint", args=["cw-course", "cw", enrollment.id])

    response = client.post(
        url, {"issue_type": "homework", "description": "My homework score is missing"}
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "coursework_leaderboard_score_breakdown", args=["cw-course", "cw", enrollment.id]
    )
    complaint = LeaderboardComplaint.objects.get(enrollment=enrollment)
    assert complaint.reporter == reporter
    assert complaint.issue_type == "homework"


def test_preferences_toggle_returns_donor_json_and_400_on_unknown_field(client):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="toggler@example.com")
    client.force_login(enrollment.user)
    url = reverse("coursework_enrollment_toggle", args=["cw-course", "cw"])

    response = client.post(
        url,
        data=json.dumps({"field": "display_on_leaderboard", "value": "false"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {"field": "display_on_leaderboard", "value": False}
    enrollment.refresh_from_db()
    assert enrollment.display_on_leaderboard is False

    unknown = client.post(
        url,
        data=json.dumps({"field": "display_height", "value": "true"}),
        content_type="application/json",
    )

    assert unknown.status_code == 400
    assert "error" in unknown.json()


def test_certificate_page_prefers_certificate_row_and_falls_back_to_legacy_url(client):
    cohort = coursework_cohort()
    row_user, row_enrollment = enrollment_for(cohort, email="cert-row@example.com")
    certificate, _issued = issue_certificate(
        row_enrollment, url="https://example.com/certs/row.pdf"
    )
    legacy_user, legacy_enrollment = enrollment_for(cohort, email="cert-legacy@example.com")
    legacy_enrollment.certificate_url = "https://example.com/certs/legacy.pdf"
    legacy_enrollment.save()
    client.force_login(row_user)

    response = client.get(reverse("coursework_certificate", args=["cw-course", "cw"]))

    assert response.status_code == 200
    assert response.context["certificate"] == certificate
    assert response.context["certificate_url"] == "https://example.com/certs/row.pdf"

    client.force_login(legacy_user)
    legacy = client.get(reverse("coursework_certificate", args=["cw-course", "cw"]))

    assert legacy.status_code == 200
    assert legacy.context["certificate"] is None
    assert legacy.context["certificate_url"] == "https://example.com/certs/legacy.pdf"
    assert Certificate.objects.count() == 1
