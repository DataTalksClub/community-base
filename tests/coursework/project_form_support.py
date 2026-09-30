"""Shared helpers for the C5.2n project submission form tests (not a test module)."""

from html.parser import HTMLParser

from django import forms
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import RequestFactory

from community_base.coursework.project_forms import ProjectSubmissionForm
from tests.coursework.test_models import enrollment_for

REPO_LINK = "https://github.com/example/repo"
COMMIT = "a1b2c3d"
FAQ_ERROR = "Use a DataTalksClub/faq issue or pull request URL."


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
