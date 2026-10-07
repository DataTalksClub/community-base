"""C5.2n: the shared project submission form's fields, toggles and validation.

The form ports CMP's "Submission details": GitHub link, commit id, learning in public links, time
spent, an optional certificate name and a status line. Saving, the deadline lock and the host
extension point are in ``test_project_submission_flow.py``.
"""

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from community_base.coursework.models import ProjectSubmission
from community_base.coursework.project_forms import ProjectSubmissionForm
from community_base.coursework.project_submission_flow import (
    build_project_submission_form,
    process_project_submission,
)
from tests.coursework.project_form_support import (
    COMMIT,
    Elements,
    field_names,
    learner,
    post_request,
    render_form,
    valid_data,
)
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db


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


def test_saved_status_time_carries_an_explicit_timezone():
    """The visible saved-at text names a timezone; the machine datetime stays ISO (#412)."""
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = learner(cohort)

    process_project_submission(post_request(user, valid_data()), project, enrollment)

    html = render_to_string(
        "coursework/_project_submission_form.html",
        {"project_form": build_project_submission_form(project, user=user, enrollment=enrollment)},
        request=RequestFactory().get("/"),
    )
    time_element = Elements(html).find("time")[0]
    assert "T" in time_element["datetime"]
    assert "UTC" in html
