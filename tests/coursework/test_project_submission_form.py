"""C5.2n: the shared, embeddable project submission form.

The form ports CMP's "Submission details": GitHub link, commit id, learning in public links, time
spent, an optional certificate name and a status line. A host site embeds the partial and calls
``process_project_submission``; it adds its own fields (DataTalks.Club's FAQ contribution) by
subclassing the form.
"""

import datetime
from html.parser import HTMLParser

import pytest
from django import forms
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import include, path, reverse
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import ProjectSubmission, SubmissionReviewState
from community_base.coursework.project_forms import (
    ProjectSubmissionForm,
    build_project_submission_form,
    process_project_submission,
)
from community_base.coursework.projects import submission_editable, submit_project
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db

REPO_LINK = "https://github.com/example/repo"
COMMIT = "a1b2c3d"

urlpatterns = [path("courses/", include("community_base.coursework.urls"))]


class Elements(HTMLParser):
    """Start tags with their attributes, so tests assert on specific elements."""

    def __init__(self, html: str):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {name: value or "" for name, value in attrs}))

    def find(self, tag=None, **attrs) -> list[dict]:
        found = []
        for name, element in self.tags:
            if tag is not None and name != tag:
                continue
            if all(element.get(key.replace("_", "-")) == value for key, value in attrs.items()):
                found.append(element)
        return found

    def with_attr(self, attribute: str) -> list[dict]:
        return [element for _name, element in self.tags if attribute in element]


def post_request(user, data):
    request = RequestFactory().post("/project/", data)
    request.user = user
    return request


def render_form(project_form) -> Elements:
    return Elements(
        render_to_string(
            "coursework/_project_submission_form.html",
            {"project_form": project_form},
            request=RequestFactory().get("/"),
        )
    )


def learner(cohort, email="form-learner@example.com"):
    return enrollment_for(cohort, email=email)


def field_names(elements: Elements) -> list[str]:
    return [element["data-project-field"] for element in elements.with_attr("data-project-field")]


def valid_data(**overrides):
    data = {"github_link": REPO_LINK, "commit_id": COMMIT}
    data.update(overrides)
    return data


# Fields and toggles.


def test_default_project_renders_the_cmp_fields_in_order_and_no_faq_field():
    cohort = coursework_cohort()
    project = make_project(cohort, faq_contribution_field=True)
    user, enrollment = learner(cohort)

    elements = render_form(build_project_submission_form(project, user=user, enrollment=enrollment))

    assert field_names(elements) == [
        "github_link",
        "commit_id",
        "learning_in_public_links",
        "time_spent",
        "certificate_name",
    ]
    assert elements.find("input", name="faq_contribution_url") == []
    assert elements.find("input", name="github_link", type="url")
    assert elements.find("details", data_commit_id_help="")
    assert len(elements.find("details", data_cb_form_help="")) == 5


def test_aisl_shape_hides_certificate_name_through_the_site_setting(settings):
    settings.COMMUNITY_BASE = {"COURSEWORK_PROJECT_CERTIFICATE_NAME_FIELD": False}
    cohort = coursework_cohort()
    project = make_project(cohort, faq_contribution_field=False, problems_comments_field=False)
    user, enrollment = learner(cohort)

    elements = render_form(build_project_submission_form(project, user=user, enrollment=enrollment))

    assert field_names(elements) == [
        "github_link",
        "commit_id",
        "learning_in_public_links",
        "time_spent",
    ]
    assert elements.find(data_project_status="not-saved")


def test_certificate_name_argument_overrides_the_site_setting(settings):
    settings.COMMUNITY_BASE = {"COURSEWORK_PROJECT_CERTIFICATE_NAME_FIELD": False}
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    form = build_project_submission_form(
        project, user=user, enrollment=enrollment, certificate_name_field=True
    )

    assert "certificate_name" in form.fields


def test_project_toggles_remove_commit_id_links_and_time_spent():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        commit_id_field=False,
        learning_in_public_cap_project=0,
        time_spent_project_field=False,
    )
    user, enrollment = learner(cohort)

    form = build_project_submission_form(
        project, user=user, enrollment=enrollment, certificate_name_field=False
    )

    assert list(form.fields) == ["github_link"]


def test_enrollment_that_opted_out_of_learning_in_public_gets_no_link_inputs():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)
    enrollment.disable_learning_in_public = True
    enrollment.save()

    form = build_project_submission_form(project, user=user, enrollment=enrollment)

    assert "learning_in_public_links" not in form.fields


# Validation parity.


@pytest.mark.parametrize(
    "link",
    [
        "not a url",
        "ftp://github.com/example/repo",
        "https://gitlab.com/example/repo",
        "https://github.com/example",
    ],
)
def test_github_link_must_be_a_github_repository(link):
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    form = build_project_submission_form(
        project, user=user, enrollment=enrollment, data=valid_data(github_link=link)
    )

    assert not form.is_valid()
    assert list(form.errors) == ["github_link"]


def test_host_can_accept_any_public_repository_host():
    class AnyHostForm(ProjectSubmissionForm):
        github_hosts = None

    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    form = build_project_submission_form(
        project,
        user=user,
        enrollment=enrollment,
        data=valid_data(github_link="https://gitlab.com/example/repo"),
        form_class=AnyHostForm,
    )

    assert form.is_valid(), form.errors


@pytest.mark.parametrize(
    ("commit_id", "valid"),
    [
        (COMMIT, True),
        ("  A1B2C3D  ", True),
        ("a" * 40, True),
        ("a1b2c3", False),
        ("a" * 41, False),
        ("not-a-sha", False),
        ("", False),
    ],
)
def test_commit_id_format(commit_id, valid):
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    form = build_project_submission_form(
        project, user=user, enrollment=enrollment, data=valid_data(commit_id=commit_id)
    )

    assert form.is_valid() is valid
    if valid:
        assert form.cleaned_data["commit_id"] == commit_id.strip()
    else:
        assert list(form.errors) == ["commit_id"]


def test_learning_in_public_links_are_deduplicated_and_capped():
    cohort = coursework_cohort()
    project = make_project(cohort, learning_in_public_cap_project=2)
    user, enrollment = learner(cohort)
    data = valid_data()
    request = RequestFactory().post(
        "/",
        {
            **data,
            "learning_in_public_links": [
                "https://example.com/1",
                " https://example.com/1 ",
                "",
                "https://example.com/2",
                "https://example.com/3",
            ],
        },
    )
    request.user = user

    outcome = process_project_submission(request, project, enrollment)

    assert outcome.action == "saved"
    assert outcome.submission.learning_in_public_links == [
        "https://example.com/1",
        "https://example.com/2",
    ]


def test_learning_in_public_link_to_a_private_host_is_rejected():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    outcome = process_project_submission(
        post_request(user, valid_data(learning_in_public_links=["http://localhost/post"])),
        project,
        enrollment,
    )

    assert outcome.action == "invalid"
    assert list(outcome.form.errors) == ["learning_in_public_links"]
    assert ProjectSubmission.objects.count() == 0


@pytest.mark.parametrize(
    ("hours", "valid"), [("3.5", True), ("0", True), ("-1", False), ("x", False)]
)
def test_time_spent_must_be_a_number_of_hours_at_least_zero(hours, valid):
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    outcome = process_project_submission(
        post_request(user, valid_data(time_spent=hours)), project, enrollment
    )

    assert (outcome.action == "saved") is valid
    if valid:
        assert outcome.submission.time_spent == float(hours)
    else:
        assert list(outcome.form.errors) == ["time_spent"]


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


FAQ_ERROR = "Use a DataTalksClub/faq issue or pull request URL."


class FaqProjectSubmissionForm(ProjectSubmissionForm):
    """What DataTalks.Club adds on top: a FAQ contribution URL with its own validation."""

    faq_contribution_url = forms.URLField(label="FAQ contribution PR or issue URL", required=False)

    def clean_faq_contribution_url(self):
        url = self.cleaned_data["faq_contribution_url"]
        if url and not url.startswith("https://github.com/DataTalksClub/faq/"):
            raise ValidationError(FAQ_ERROR)
        return url

    def apply_extra_fields(self, submission):
        submission.faq_contribution_url = self.cleaned_data["faq_contribution_url"]


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
