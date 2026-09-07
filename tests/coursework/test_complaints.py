import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.complaints import (
    create_leaderboard_complaint,
    resolve_leaderboard_complaint,
)
from community_base.coursework.models import LeaderboardComplaint
from tests.coursework.test_models import coursework_cohort, enrollment_for

pytestmark = pytest.mark.django_db


def test_create_leaderboard_complaint_defaults_to_open(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="reporter@example.com")
    reporter = User.objects.create_user(email="member@example.com")

    complaint = create_leaderboard_complaint(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=LeaderboardComplaint.IssueType.LEARNING_IN_PUBLIC,
        description="The link is not about the course.",
    )

    assert complaint.pk is not None
    assert complaint.enrollment == enrollment
    assert complaint.reporter == reporter
    assert complaint.issue_type == LeaderboardComplaint.IssueType.LEARNING_IN_PUBLIC
    assert complaint.description == "The link is not about the course."
    assert complaint.resolved is False
    assert complaint.resolved_at is None
    assert complaint.resolved_by is None


def test_resolve_leaderboard_complaint_sets_fields_with_update(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="complainant@example.com")
    reporter = User.objects.create_user(email="first@example.com")
    staff = User.objects.create_user(email="staff@example.com")
    complaint = create_leaderboard_complaint(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=LeaderboardComplaint.IssueType.OTHER,
        description="Score looks wrong.",
    )
    resolved_at = timezone.now() - datetime.timedelta(hours=1)

    result = resolve_leaderboard_complaint(
        complaint=complaint, resolved_by=staff, resolved_at=resolved_at
    )

    assert result == complaint
    complaint.refresh_from_db()
    assert complaint.resolved is True
    assert complaint.resolved_at == resolved_at
    assert complaint.resolved_by == staff


def test_resolve_leaderboard_complaint_defaults_resolved_at_to_now(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="second@example.com")
    reporter = User.objects.create_user(email="second-reporter@example.com")
    staff = User.objects.create_user(email="second-staff@example.com")
    complaint = create_leaderboard_complaint(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=LeaderboardComplaint.IssueType.HOMEWORK,
        description="Another issue.",
    )
    before = timezone.now()

    resolve_leaderboard_complaint(complaint=complaint, resolved_by=staff)

    complaint.refresh_from_db()
    assert complaint.resolved_at is not None
    assert before <= complaint.resolved_at <= timezone.now()


def test_resolution_never_touches_scores_or_leaderboard_cache(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="third@example.com")
    enrollment.total_score = 42
    enrollment.position_on_leaderboard = 3
    enrollment.save()
    cache.set(f"leaderboard:{cohort.id}", ["cached"], 60)
    reporter = User.objects.create_user(email="third-reporter@example.com")
    staff = User.objects.create_user(email="third-staff@example.com")
    complaint = create_leaderboard_complaint(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=LeaderboardComplaint.IssueType.PROJECT,
        description="Project score dispute.",
    )

    resolve_leaderboard_complaint(complaint=complaint, resolved_by=staff)

    enrollment.refresh_from_db()
    assert enrollment.total_score == 42
    assert enrollment.position_on_leaderboard == 3
    assert cache.get(f"leaderboard:{cohort.id}") == ["cached"]


def test_complaint_ordering_lists_open_first(db):
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="fourth@example.com")
    reporter = User.objects.create_user(email="fourth-reporter@example.com")
    staff = User.objects.create_user(email="fourth-staff@example.com")
    resolved = create_leaderboard_complaint(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=LeaderboardComplaint.IssueType.OTHER,
        description="Resolved already.",
    )
    open_complaint = create_leaderboard_complaint(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=LeaderboardComplaint.IssueType.OTHER,
        description="Still open.",
    )
    resolve_leaderboard_complaint(complaint=resolved, resolved_by=staff)

    complaints = list(LeaderboardComplaint.objects.all())

    assert complaints == [open_complaint, resolved]
