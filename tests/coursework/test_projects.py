import datetime

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import PeerReview, Project, ProjectSubmission, ProjectVote
from community_base.coursework.projects import (
    clean_learning_in_public_links,
    delete_project_submission,
    peer_review_lip_score,
    project_lip_score,
    submit_project,
)
from community_base.coursework.votes import (
    PROJECT_VOTES_PER_PROJECT,
    get_project_vote_counts,
    get_voted_submission_ids,
    update_project_vote,
)
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import (
    coursework_cohort,
    create_project_submission,
    enrollment_for,
)

pytestmark = pytest.mark.django_db


def make_project(cohort, **values):
    values.setdefault("slug", "final")
    values.setdefault("title", "Final project")
    values.setdefault("submission_due_date", timezone.now() + datetime.timedelta(days=7))
    values.setdefault("peer_review_due_date", timezone.now() + datetime.timedelta(days=14))
    return Project.objects.create(cohort=cohort, **values)


def lip_links(count):
    return [f"https://example.com/post/{index}" for index in range(count)]


def test_clean_learning_in_public_links_strips_dedupes_and_caps():
    links = ["", "  https://a.example  ", "https://a.example", "https://b.example"]

    assert clean_learning_in_public_links(links, 1) == ["https://a.example"]
    assert clean_learning_in_public_links(["https://a.example", "https://b.example"], 5) == [
        "https://a.example",
        "https://b.example",
    ]


def test_clean_learning_in_public_links_rejects_non_public_targets():
    with pytest.raises(ValidationError):
        clean_learning_in_public_links(["ftp://example.com/post"], 5)
    with pytest.raises(ValidationError):
        clean_learning_in_public_links(["http://127.0.0.1/post"], 5)
    with pytest.raises(ValidationError):
        clean_learning_in_public_links(["not a url"], 5)


def test_submit_project_captures_github_commit_and_caps_links():
    cohort = coursework_cohort()
    project = make_project(cohort)
    _user, enrollment = enrollment_for(cohort, email="submitter@example.com")

    submission, created = submit_project(
        project,
        enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
        learning_in_public_links=[
            "  https://example.com/a  ",
            "https://example.com/a",
            *lip_links(20),
        ],
        time_spent=5.5,
        problems_comments="  none  ",
        faq_contribution_url="  https://example.com/faq  ",
    )

    assert created is True
    assert submission.github_link == "https://github.com/example/repo"
    assert submission.commit_id == "a" * 40
    assert submission.learning_in_public_links == ["https://example.com/a", *lip_links(13)]
    assert submission.time_spent == 5.5
    assert submission.problems_comments == "none"
    assert submission.faq_contribution_url == "https://example.com/faq"


def test_submit_project_updates_the_same_submission_row():
    cohort = coursework_cohort()
    project = make_project(cohort)
    _user, enrollment = enrollment_for(cohort, email="resubmit@example.com")

    first, _created = submit_project(
        project,
        enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
    )
    second, created = submit_project(
        project,
        enrollment,
        github_link="https://github.com/example/other",
        commit_id="b" * 40,
    )

    assert created is False
    assert second.id == first.id
    assert second.submitted_at >= first.submitted_at
    assert second.github_link == "https://github.com/example/other"
    assert ProjectSubmission.objects.filter(project=project).count() == 1


def test_submit_project_honours_field_toggles():
    cohort = coursework_cohort()
    project = make_project(
        cohort,
        faq_contribution_field=False,
        problems_comments_field=False,
        time_spent_project_field=False,
    )
    _user, enrollment = enrollment_for(cohort, email="toggles@example.com")

    submission, _created = submit_project(
        project,
        enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
        time_spent=3.0,
        problems_comments="worried",
        faq_contribution_url="https://example.com/faq",
    )

    assert submission.time_spent is None
    assert submission.problems_comments == ""
    assert submission.faq_contribution_url is None


def test_project_lip_score_respects_cap_and_disabled_enrollment():
    cohort = coursework_cohort()
    project = make_project(cohort)
    _user, enrollment = enrollment_for(cohort, email="lip@example.com")
    submission = create_project_submission(project, enrollment, enrollment.user)
    submission.learning_in_public_links = lip_links(20)
    submission.save()

    assert project_lip_score(submission, project) == project.learning_in_public_cap_project

    enrollment.disable_learning_in_public = True
    enrollment.save()
    submission.refresh_from_db()
    assert project_lip_score(submission, project) == 0


def test_peer_review_lip_score_sums_links_capped_per_review():
    cohort = coursework_cohort()
    project = make_project(cohort)
    reviewer_user, reviewer_enrollment = enrollment_for(cohort, email="reviewer@example.com")
    target_user, target_enrollment = enrollment_for(cohort, email="target@example.com")
    reviewer = create_project_submission(project, reviewer_enrollment, reviewer_user)
    target = create_project_submission(project, target_enrollment, target_user)
    PeerReview.objects.create(
        submission_under_evaluation=target,
        reviewer=reviewer,
        learning_in_public_links=lip_links(5),
    )
    PeerReview.objects.create(
        submission_under_evaluation=target,
        reviewer=reviewer,
        learning_in_public_links=["https://example.com/one"],
    )
    reviewed = list(PeerReview.objects.filter(reviewer=reviewer))

    # cap_review is 2: the five-link review counts 2, the one-link review counts 1.
    assert peer_review_lip_score(reviewer, project, reviewed) == 3


def test_delete_project_submission_removes_only_the_real_submission():
    cohort = coursework_cohort()
    project = make_project(cohort)
    user, enrollment = enrollment_for(cohort, email="deleter@example.com")
    submission = create_project_submission(project, enrollment, user)

    assert delete_project_submission(project, user) is True
    assert not ProjectSubmission.objects.filter(id=submission.id).exists()
    assert delete_project_submission(project, user) is False


def test_update_project_vote_caps_votes_per_project():
    cohort = coursework_cohort()
    project = make_project(cohort)
    other_project = make_project(cohort, slug="other")
    voter = User.objects.create_user(email="voter@example.com")
    Enrollment.objects.create(user=voter, cohort=cohort)
    submitters = [enrollment_for(cohort, email=f"voted{index}@example.com") for index in range(4)]
    submissions = [
        create_project_submission(project, enrollment, user) for user, enrollment in submitters
    ]
    other_submission = create_project_submission(other_project, submitters[0][1], submitters[0][0])

    for submission in submissions[:PROJECT_VOTES_PER_PROJECT]:
        assert update_project_vote(voter, submission) is True
    assert update_project_vote(voter, submissions[3]) is False
    assert update_project_vote(voter, other_submission) is True

    # Removing a vote frees a slot within the same project's cap.
    assert update_project_vote(voter, submissions[0], action="remove") is True
    assert update_project_vote(voter, submissions[3]) is True


def test_update_project_vote_is_idempotent_per_submission():
    cohort = coursework_cohort()
    project = make_project(cohort)
    voter = User.objects.create_user(email="once@example.com")
    user, enrollment = enrollment_for(cohort, email="voted@example.com")
    submission = create_project_submission(project, enrollment, user)

    assert update_project_vote(voter, submission) is True
    assert update_project_vote(voter, submission) is False
    assert ProjectVote.objects.filter(voter=voter, submission=submission).count() == 1


def test_vote_lookups_per_cohort():
    cohort = coursework_cohort()
    other_cohort = coursework_cohort(slug="cw-votes-other")
    project = make_project(cohort)
    other_project = make_project(other_cohort)
    voter = User.objects.create_user(email="lookup@example.com")
    Enrollment.objects.create(user=voter, cohort=cohort)
    user, enrollment = enrollment_for(cohort, email="looked-up@example.com")
    submission = create_project_submission(project, enrollment, user)
    other_user, other_enrollment = enrollment_for(other_cohort, email="elsewhere@example.com")
    other_submission = create_project_submission(other_project, other_enrollment, other_user)
    update_project_vote(voter, submission)
    update_project_vote(voter, other_submission)

    assert get_voted_submission_ids(voter, cohort) == {submission.id}
    assert get_project_vote_counts(voter, cohort) == {project.id: 1}
    assert get_voted_submission_ids(AnonymousUser(), cohort) == set()
    assert get_project_vote_counts(AnonymousUser(), cohort) == {}
