"""Tests for GitHub commit resolution and ProjectSubmissionForm commit capture."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.github_commit import (
    GitHubUnavailable,
    InvalidRepositoryUrl,
    RepositoryNotFound,
    github_commit_url,
    parse_github_url,
    resolve_commit,
)
from community_base.coursework.models import Project, ProjectSubmission
from community_base.coursework.project_forms import ProjectSubmissionForm, update_commit_action
from community_base.curriculum.models import Cohort, Course, Enrollment


def test_parse_github_url_and_commit_url():
    assert parse_github_url("https://github.com/octocat/Hello-World") == (
        "octocat",
        "Hello-World",
        "HEAD",
    )
    assert parse_github_url("https://www.github.com/octocat/repo.git/tree/main/sub") == (
        "octocat",
        "repo",
        "main/sub",
    )
    assert (
        github_commit_url("https://github.com/octocat/repo", "abc1234")
        == "https://github.com/octocat/repo/commit/abc1234"
    )
    assert github_commit_url("https://gitlab.com/a/b", "abc1234") == ""
    with pytest.raises(InvalidRepositoryUrl):
        parse_github_url("https://gitlab.com/a/b")


def test_resolve_commit_responses():
    ok_resp = SimpleNamespace(status_code=200, headers={}, json=lambda: {"sha": "ABCDEF1234567"})
    with patch("community_base.coursework.github_commit.requests.get", return_value=ok_resp) as m:
        sha = resolve_commit(
            "https://github.com/octocat/repo",
            auth_headers=lambda: {"Authorization": "Bearer tok"},
        )
    assert sha == "abcdef1234567"
    assert m.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    not_found = SimpleNamespace(status_code=404, headers={})
    with patch("community_base.coursework.github_commit.requests.get", return_value=not_found):
        with pytest.raises(RepositoryNotFound):
            resolve_commit("https://github.com/octocat/missing")

    rate_limited = SimpleNamespace(status_code=403, headers={"X-RateLimit-Remaining": "0"})
    with patch("community_base.coursework.github_commit.requests.get", return_value=rate_limited):
        with pytest.raises(GitHubUnavailable):
            resolve_commit("https://github.com/octocat/repo")

    with patch(
        "community_base.coursework.github_commit.requests.get",
        side_effect=requests.Timeout("slow"),
    ):
        with pytest.raises(GitHubUnavailable):
            resolve_commit("https://github.com/octocat/repo")


@pytest.mark.django_db
def test_project_submission_form_resolve_commit_and_update_action():
    now = timezone.now()
    course = Course.objects.create(slug="gh", title="GH")
    cohort = Cohort.objects.create(
        course=course,
        slug="c1",
        title="C1",
        mode="cohort",
        start_date=now.date(),
        end_date=(now + timedelta(days=30)).date(),
    )
    project = Project.objects.create(
        cohort=cohort,
        slug="p1",
        title="P1",
        commit_id_field=False,
        submission_due_date=now + timedelta(days=7),
        peer_review_due_date=now + timedelta(days=14),
    )
    user = User.objects.create_user(email="u@example.com", first_name="Ada", last_name="Lovelace")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)

    with patch(
        "community_base.coursework.project_forms.resolve_github_commit",
        return_value="1234567890abcdef",
    ):
        form = ProjectSubmissionForm(
            data={"github_link": "https://github.com/octocat/repo"},
            project=project,
            enrollment=enrollment,
            user=user,
            resolve_commit=True,
        )
        assert form.initial["certificate_name"] == "Ada Lovelace"
        assert form.is_valid(), form.errors
        sub, created = form.save()
        assert created is True
        assert sub.commit_id == "1234567890abcdef"

    with patch(
        "community_base.coursework.project_forms.resolve_github_commit",
        return_value="fedcba0987654321",
    ):
        edit_form = ProjectSubmissionForm(
            data={"github_link": "https://github.com/octocat/repo"},
            project=project,
            submission=sub,
            enrollment=enrollment,
            user=user,
        )
        ok, err = update_commit_action(edit_form, sub)
        assert ok is True
        assert err == ""
        sub.refresh_from_db()
        assert sub.commit_id == "fedcba0987654321"
        assert isinstance(sub, ProjectSubmission)
