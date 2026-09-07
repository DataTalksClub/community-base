import datetime

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.hooks import (
    _default_project_leaderboard_updater,
    default_display_name_generator,
    discard_event,
)
from community_base.coursework.hooks import hooks as coursework_hooks
from community_base.coursework.models import PeerReview
from community_base.coursework.review import (
    ProjectActionStatus,
    add_volunteer_peer_review,
    assign_peer_reviews_for_project,
    remove_volunteer_peer_review,
    score_project,
)
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_peer_review import (
    close_review_window,
    make_criteria,
    make_submissions,
    submit_all_reviews,
)
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db


def test_hooks_default_to_discard():
    assert coursework_hooks.peer_reviews_assigned is discard_event
    assert coursework_hooks.optional_review_added is discard_event
    assert coursework_hooks.project_scored is discard_event


def test_leaderboard_and_name_defaults_point_at_package_services():
    assert coursework_hooks.project_leaderboard_updater is _default_project_leaderboard_updater
    assert coursework_hooks.display_name_generator is default_display_name_generator
    assert coursework_hooks.homework_submitted is discard_event
    assert coursework_hooks.project_submitted is discard_event
    assert coursework_hooks.registration_submitted is discard_event
    assert coursework_hooks.certificate_issued is discard_event


def test_assignment_and_scoring_fire_configured_hooks(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_PEER_REVIEWS_ASSIGNED": lambda **event: seen.append(("assigned", event)),
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER": lambda **event: seen.append(
            ("leaderboard", event)
        ),
        "COURSEWORK_PROJECT_SCORED": lambda **event: seen.append(("scored", event)),
    }

    cohort = coursework_cohort()
    project = make_project(
        cohort,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=1),
    )
    make_criteria(project)
    make_submissions(project, cohort, 3)

    status, _message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.OK

    submit_all_reviews(project)
    close_review_window(project)
    status, _message = score_project(project)
    assert status is ProjectActionStatus.OK

    names = [name for name, _event in seen]
    assert names == ["assigned", "leaderboard", "scored"]
    assert seen[0][1]["project"] == project
    assert (
        seen[0][1]["review_count"]
        == PeerReview.objects.filter(
            submission_under_evaluation__project=project, optional=False
        ).count()
    )
    assert seen[2][1]["passed_count"] == 3


def test_optional_review_hook_fires_once_per_review(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_OPTIONAL_REVIEW_ADDED": lambda **event: seen.append(event["review"].id),
    }

    cohort = coursework_cohort()
    project = make_project(cohort)
    (submission,) = make_submissions(project, cohort, 1)
    volunteer = User.objects.create_user(email="volunteer-hooks@example.com")

    review, created = add_volunteer_peer_review(project, volunteer, submission)
    review_again, created_again = add_volunteer_peer_review(project, volunteer, submission)

    assert created and not created_again
    assert review.id == review_again.id
    assert seen == [review.id]


def test_failure_and_deletion_hooks_fire_with_reason(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_PEER_REVIEWS_ASSIGNMENT_FAILED": lambda **event: seen.append(
            ("assignment_failed", event)
        ),
        "COURSEWORK_PROJECT_SCORING_FAILED": lambda **event: seen.append(("scoring_failed", event)),
        "COURSEWORK_OPTIONAL_REVIEW_DELETED": lambda **event: seen.append(
            ("optional_deleted", event)
        ),
    }

    cohort = coursework_cohort()
    project = make_project(cohort)
    submissions = make_submissions(project, cohort, 2)

    status, message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.FAIL

    cohort.project_passing_score = 0
    cohort.save()
    status, _message = score_project(project)
    assert status is ProjectActionStatus.FAIL

    volunteer = User.objects.create_user(email="volunteer-remove@example.com")
    review, _created = add_volunteer_peer_review(project, volunteer, submissions[0])
    assert remove_volunteer_peer_review(project, volunteer, review.id) == 1
    assert remove_volunteer_peer_review(project, volunteer, review.id) == 0

    names = [name for name, _event in seen]
    assert names == ["assignment_failed", "scoring_failed", "optional_deleted"]
    assert "submission due date is in the future" in seen[0][1]["reason"]
    assert "no points to pass" in seen[1][1]["reason"]
    assert seen[2][1]["review_id"] == review.id
