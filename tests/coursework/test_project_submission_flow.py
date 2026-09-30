"""C5.2n: saving, the deadline lock, embedding and the host extension point.

A host site embeds the partial and calls ``process_project_submission``; it adds its own fields
(DataTalks.Club's FAQ contribution) by subclassing the form.
"""

import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import include, path, reverse
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import ProjectSubmission, SubmissionReviewState
from community_base.coursework.project_submission_flow import (
    build_project_submission_form,
    process_project_submission,
)
from community_base.coursework.projects import submission_editable, submit_project
from tests.coursework.project_form_support import (
    COMMIT,
    FAQ_ERROR,
    REPO_LINK,
    Elements,
    FaqProjectSubmissionForm,
    field_names,
    learner,
    post_request,
    render_form,
    valid_data,
)
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db

urlpatterns = [path("courses/", include("community_base.coursework.urls"))]


# Saving, status line and the deadline lock.


def test_save_then_update_keeps_one_row_and_the_status_line_says_saved():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    first = process_project_submission(post_request(user, valid_data()), project, enrollment)
    second = process_project_submission(
        post_request(user, valid_data(commit_id="b2c3d4e")), project, enrollment
    )

    assert (first.action, first.created) == ("saved", True)
    assert (second.action, second.created) == ("saved", False)
    submission = ProjectSubmission.objects.get(project=project, student=user)
    assert submission.commit_id == "b2c3d4e"
    elements = render_form(build_project_submission_form(project, user=user, enrollment=enrollment))
    assert elements.find(data_project_status="saved")
    assert elements.find("button", data_project_save="")
    assert elements.find("button", name="action", value="delete")


def test_certificate_name_is_saved_on_the_enrollment():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    process_project_submission(
        post_request(user, valid_data(certificate_name="  Ada Lovelace ")), project, enrollment
    )

    enrollment.refresh_from_db()
    assert enrollment.certificate_name == "Ada Lovelace"


def test_saving_keeps_stored_fields_the_shared_form_does_not_show():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)
    submission, _created = submit_project(
        project,
        enrollment,
        github_link=REPO_LINK,
        commit_id=COMMIT,
        problems_comments="Imported description",
        faq_contribution_url="https://github.com/DataTalksClub/faq/issues/1",
    )

    outcome = process_project_submission(
        post_request(user, valid_data(commit_id="b2c3d4e")), project, enrollment
    )

    assert outcome.action == "saved"
    submission.refresh_from_db()
    assert submission.problems_comments == "Imported description"
    assert submission.faq_contribution_url == "https://github.com/DataTalksClub/faq/issues/1"


def test_edits_lock_after_the_deadline():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)
    process_project_submission(post_request(user, valid_data()), project, enrollment)
    project.submission_due_date = timezone.now() - datetime.timedelta(minutes=1)
    project.save()

    outcome = process_project_submission(
        post_request(user, valid_data(commit_id="b2c3d4e")), project, enrollment
    )
    removed = process_project_submission(
        post_request(user, {"action": "delete"}), project, enrollment
    )

    assert outcome.action == "closed"
    assert removed.action == "closed"
    assert ProjectSubmission.objects.get(project=project).commit_id == COMMIT
    elements = render_form(build_project_submission_form(project, user=user, enrollment=enrollment))
    assert elements.find(data_project_closed="")
    assert elements.find("button", data_project_save="") == []
    assert all("disabled" in element for element in elements.find("input", name="commit_id"))


def test_pooled_submission_locks_once_it_joins_a_review_batch():
    cohort = coursework_cohort(slug="pool", mode="self_paced")
    project = make_project(cohort, submission_due_date=None, peer_review_due_date=None)
    user, enrollment = learner(cohort)
    submission, _created = submit_project(
        project, enrollment, github_link=REPO_LINK, commit_id=COMMIT
    )

    assert submission_editable(project, submission) is True
    submission.review_state = SubmissionReviewState.IN_REVIEW.value
    submission.save()

    outcome = process_project_submission(
        post_request(user, valid_data(commit_id="b2c3d4e")), project, enrollment
    )

    assert outcome.action == "closed"


def test_anonymous_viewer_gets_a_read_only_preview():
    cohort = coursework_cohort()
    project = make_project(cohort)
    form = build_project_submission_form(project, user=AnonymousUser())
    elements = render_form(form)

    assert form.editable is False
    assert elements.find(data_project_sign_in="")
    assert elements.find("button", data_project_save="") == []


def test_remove_deletes_the_submission():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)
    process_project_submission(post_request(user, valid_data()), project, enrollment)

    outcome = process_project_submission(
        post_request(user, {"action": "delete"}), project, enrollment
    )

    assert outcome.action == "deleted"
    assert ProjectSubmission.objects.count() == 0
    assert outcome.form.has_submission is False


def test_save_and_delete_fire_the_project_hooks(settings, django_capture_on_commit_callbacks):
    events = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_PROJECT_SUBMITTED": lambda **event: events.append(("submitted", event)),
        "COURSEWORK_PROJECT_DELETED": lambda **event: events.append(("deleted", event)),
    }
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    with django_capture_on_commit_callbacks(execute=True):
        saved = process_project_submission(post_request(user, valid_data()), project, enrollment)
    with django_capture_on_commit_callbacks(execute=True):
        process_project_submission(post_request(user, {"action": "delete"}), project, enrollment)

    assert events == [
        ("submitted", {"submission": saved.submission, "created": True}),
        ("deleted", {"project": project, "user": user}),
    ]


# Embedding and the host extension point.


def test_partial_posts_to_the_host_action_url():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    elements = render_form(
        build_project_submission_form(
            project, user=user, enrollment=enrollment, action_url="/courses/x/unit/project/"
        )
    )

    assert elements.find("form", data_project_form="", action="/courses/x/unit/project/")


def test_host_added_field_renders_validates_and_saves():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)
    faq_url = "https://github.com/DataTalksClub/faq/pull/7"

    elements = render_form(
        build_project_submission_form(
            project, user=user, enrollment=enrollment, form_class=FaqProjectSubmissionForm
        )
    )
    rejected = process_project_submission(
        post_request(user, valid_data(faq_contribution_url="https://github.com/other/faq/pull/7")),
        project,
        enrollment,
        form_class=FaqProjectSubmissionForm,
    )
    saved = process_project_submission(
        post_request(user, valid_data(faq_contribution_url=faq_url)),
        project,
        enrollment,
        form_class=FaqProjectSubmissionForm,
    )

    names = field_names(elements)
    assert names.index("faq_contribution_url") == names.index("time_spent") + 1
    assert elements.find("input", name="faq_contribution_url")
    assert rejected.action == "invalid"
    assert rejected.form.errors["faq_contribution_url"] == [FAQ_ERROR]
    assert saved.action == "saved"
    assert ProjectSubmission.objects.get(project=project).faq_contribution_url == faq_url


def test_host_extra_fields_template_replaces_the_generic_rendering():
    class TemplatedForm(FaqProjectSubmissionForm):
        extra_fields_template = "coursework_tests/_extra_project_fields.html"

    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    elements = render_form(
        build_project_submission_form(
            project, user=user, enrollment=enrollment, form_class=TemplatedForm
        )
    )

    assert elements.find("div", data_host_extra_field="faq_contribution_url")
    assert "faq_contribution_url" not in field_names(elements)


def test_model_error_raised_by_a_host_field_is_reported_on_the_form():
    class TooLongFaqForm(FaqProjectSubmissionForm):
        def apply_extra_fields(self, submission):
            submission.faq_contribution_url = "https://github.com/DataTalksClub/faq/" + "x" * 250

    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    outcome = process_project_submission(
        post_request(user, valid_data()), project, enrollment, form_class=TooLongFaqForm
    )

    assert outcome.action == "invalid"
    assert "faq_contribution_url" in outcome.form.errors
    assert ProjectSubmission.objects.count() == 0


# The package page uses the same form.


@pytest.fixture
def coursework_urlconf(settings):
    settings.ROOT_URLCONF = __name__


def test_package_project_page_rerenders_invalid_input_with_errors(client, coursework_urlconf):
    cohort = coursework_cohort()
    project = make_project(cohort)
    user = User.objects.create_user(email="page-poster@example.com")
    client.force_login(user)
    url = reverse("coursework_project", args=["cw-course", "cw", project.slug])

    response = client.post(url, valid_data(commit_id="zzz"))

    assert response.status_code == 200
    elements = Elements(response.content.decode())
    assert elements.find("p", data_field_error="commit_id")
    assert elements.find("input", name="github_link", value=REPO_LINK)
    assert ProjectSubmission.objects.count() == 0
