import datetime

import pytest
from django.utils import timezone

from community_base.config import service
from community_base.coursework.automation import COURSEWORK_AUTOMATION_KEY
from community_base.coursework.models import (
    PeerReview,
    ProjectEvaluationScore,
    ProjectState,
    ProjectSubmission,
)
from community_base.coursework.review import (
    ProjectActionStatus,
    assign_peer_reviews_for_project,
    calculate_project_scoring,
    persist_scored_submissions,
    score_project,
)
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_peer_review import make_criteria, make_submissions, submit_all_reviews
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def reset_runtime_config():
    service.runtime.reset()
    yield
    service.runtime.reset()


def disable_automation():
    service.set(COURSEWORK_AUTOMATION_KEY, False, "test:intentional-api")


def scoring_fixture(slug):
    cohort = coursework_cohort(slug=slug)
    project = make_project(
        cohort,
        slug=slug,
        number_of_peers_to_evaluate=2,
        submission_due_date=timezone.now() - datetime.timedelta(days=2),
    )
    make_criteria(project)
    submissions = make_submissions(project, cohort, 3, prefix=slug)
    status, _message = assign_peer_reviews_for_project(project)
    assert status is ProjectActionStatus.OK
    submit_all_reviews(project)
    return project, submissions


def test_explicit_calculation_and_persistence_remain_available_when_disabled():
    project, submissions = scoring_fixture("guard-explicit-scoring")
    reviews = PeerReview.objects.filter(submission_under_evaluation__project=project)
    disable_automation()

    calculation = calculate_project_scoring(project, reviews)
    persist_scored_submissions(calculation)

    assert len(calculation.submissions_to_update) == 3
    assert ProjectEvaluationScore.objects.filter(submission__in=submissions).exists()
    assert ProjectSubmission.objects.filter(
        pk__in=[row.pk for row in submissions], passed=True
    ).count()


def test_operator_deadline_scoring_and_hooks_remain_available_when_disabled(settings):
    scored = []
    leaderboard = []
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "COURSEWORK_PROJECT_SCORED": lambda **event: scored.append(event),
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER": lambda **event: leaderboard.append(event),
    }
    project, submissions = scoring_fixture("guard-deadline-scoring")
    project.peer_review_due_date = timezone.now() - datetime.timedelta(days=1)
    project.save(update_fields=["peer_review_due_date"])
    disable_automation()

    status, _message = score_project(project)

    assert status is ProjectActionStatus.OK
    project.refresh_from_db()
    assert project.state == ProjectState.COMPLETED.value
    assert ProjectEvaluationScore.objects.filter(submission__in=submissions).exists()
    assert scored == [{"project": project, "passed_count": 3}]
    assert leaderboard == [{"project": project}]
