"""Donor-parity tests for wrapped statistics calculation and persistence.

Mirrors the `dtc-website` wrapped test family against the package surface
`community_base.coursework.wrapped`: `test_wrapped_statistics.py` (platform
statistics, leaderboard), `test_wrapped_user_statistics.py` (per-user rows),
`test_wrapped_recalculation.py` (forced idempotence) and the service assertions
behind `test_wrapped_views.py` (visible-row selection, the no-activity path).
The donor's cohort-only model is the package Course + Cohort pair, and the
donor's `cohort_year`/`cohort_identifier` JSON keys become `cohort_slug`.
"""

import datetime

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import ProjectSubmission, Submission, UserWrappedStatistics
from community_base.coursework.wrapped import (
    calculate_wrapped_statistics,
    get_user_wrapped,
    replace_user_wrapped_statistics,
)
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import homework as make_homework
from tests.coursework.test_projects import make_project
from tests.curriculum.test_models import make_cohort, make_course

pytestmark = pytest.mark.django_db


def in_2025(month=6, day=1):
    naive_date = datetime.datetime(year=2025, month=month, day=day, hour=12, minute=0, second=0)
    return timezone.make_aware(naive_date)


def in_2024(month=6, day=1):
    naive_date = datetime.datetime(year=2024, month=month, day=day, hour=12, minute=0, second=0)
    return timezone.make_aware(naive_date)


class WrappedFixture:
    """The donor `wrapped_statistics_base.py` fixture family, package-flavoured."""

    def __init__(self):
        self.course = make_course(slug="wrapped-course", title="Wrapped Course")
        self.cohort = make_cohort(self.course, slug="2026", title="Wrapped cohort")
        self.homework = make_homework(self.cohort, slug="hw1", title="HW 1", due_date=in_2025())
        self.project = make_project(
            self.cohort,
            slug="proj1",
            title="Project 1",
            submission_due_date=in_2025(7, 1),
            peer_review_due_date=in_2025(7, 8),
        )

    def user(self, email):
        return User.objects.create_user(email=email)

    def enrollment(self, user, display_name, total_score, certificate_url=""):
        return Enrollment.objects.create(
            user=user,
            cohort=self.cohort,
            display_name=display_name,
            total_score=total_score,
            certificate_url=certificate_url,
        )

    def homework_submission(
        self,
        user,
        enrollment,
        lecture_hours,
        homework_hours,
        learning_links=None,
        faq_url="",
        submitted_at=None,
    ):
        return Submission.objects.create(
            homework=self.homework,
            student=user,
            enrollment=enrollment,
            time_spent_lectures=lecture_hours,
            time_spent_homework=homework_hours,
            learning_in_public_links=learning_links or [],
            faq_contribution_url=faq_url,
            submitted_at=submitted_at or in_2025(),
        )

    def project_submission(self, user, enrollment, submitted_at=None):
        return ProjectSubmission.objects.create(
            project=self.project,
            student=user,
            enrollment=enrollment,
            time_spent=5.0,
            learning_in_public_links=["https://x/3"],
            submitted_at=submitted_at or in_2025(7, 2),
        )

    def create_alice_activity(self):
        self.alice = self.user("alice@test.com")
        self.alice_enrollment = self.enrollment(
            self.alice, "Alice", 100, certificate_url="https://certs.example.com/alice"
        )
        self.homework_submission(
            self.alice,
            self.alice_enrollment,
            lecture_hours=2.0,
            homework_hours=3.0,
            learning_links=["https://x/1", "https://x/2"],
            faq_url="https://faq/alice",
        )
        self.project_submission(self.alice, self.alice_enrollment)

    def create_bob_activity(self):
        self.bob = self.user("bob@test.com")
        self.bob_enrollment = self.enrollment(self.bob, "Bob", 50)
        self.homework_submission(
            self.bob, self.bob_enrollment, lecture_hours=1.0, homework_hours=1.0
        )


def donor_fixture():
    fixture = WrappedFixture()
    fixture.create_alice_activity()
    fixture.create_bob_activity()
    stats = calculate_wrapped_statistics(year=2025, force=True)
    return fixture, stats


def test_platform_statistics():
    _, stats = donor_fixture()

    assert stats.total_participants == 2
    assert stats.total_enrollments == 2
    # Alice 2+3+5 = 10, Bob 1+1 = 2 -> 12 hours total
    assert stats.total_hours == 12.0
    assert stats.total_certificates == 1
    assert stats.total_points == 150
    assert stats.course_stats == [
        {
            "title": "Wrapped Course",
            "slug": "2026",
            "course_slug": "wrapped-course",
            "cohort_slug": "2026",
            "enrollment_count": 2,
        }
    ]


def test_leaderboard():
    _, stats = donor_fixture()

    leaderboard = stats.leaderboard

    assert len(leaderboard) == 2
    assert leaderboard[0]["display_name"] == "Alice"
    assert leaderboard[0]["rank"] == 1
    assert leaderboard[0]["total_score"] == 100
    assert leaderboard[1]["display_name"] == "Bob"
    assert leaderboard[1]["rank"] == 2


def test_user_statistics_alice():
    _, stats = donor_fixture()

    alice_stats = UserWrappedStatistics.objects.get(wrapped=stats, user__email="alice@test.com")

    assert alice_stats.total_points == 100
    assert alice_stats.total_hours == 10.0
    assert alice_stats.homework_count == 1
    assert alice_stats.project_count == 1
    assert alice_stats.peer_reviews_given == 0
    assert alice_stats.learning_in_public_count == 3
    assert alice_stats.faq_contributions_count == 1
    assert alice_stats.certificates_earned == 1
    assert alice_stats.rank == 1
    assert alice_stats.display_name == "Alice"


def test_user_statistics_bob():
    _, stats = donor_fixture()

    bob_stats = UserWrappedStatistics.objects.get(wrapped=stats, user__email="bob@test.com")

    assert bob_stats.total_points == 50
    assert bob_stats.total_hours == 2.0
    assert bob_stats.homework_count == 1
    assert bob_stats.project_count == 0
    assert bob_stats.learning_in_public_count == 0
    assert bob_stats.faq_contributions_count == 0
    assert bob_stats.certificates_earned == 0
    assert bob_stats.rank == 2
    assert bob_stats.display_name == "Bob"


def test_idempotent_forced_recalculation():
    _, stats = donor_fixture()

    again = calculate_wrapped_statistics(year=2025, force=True)

    assert again.id == stats.id
    assert UserWrappedStatistics.objects.filter(wrapped=again).count() == 2


def test_calculate_without_force_returns_the_existing_row_and_stays_stale():
    fixture, stats = donor_fixture()
    charlie = fixture.user("charlie@test.com")
    charlie_enrollment = fixture.enrollment(charlie, "Charlie", 10)
    fixture.homework_submission(charlie, charlie_enrollment, lecture_hours=1.0, homework_hours=1.0)

    stale = calculate_wrapped_statistics(year=2025)

    assert stale.id == stats.id
    assert stale.total_participants == 2
    assert not UserWrappedStatistics.objects.filter(wrapped=stats, user=charlie).exists()

    fresh = calculate_wrapped_statistics(year=2025, force=True)

    assert fresh.id == stats.id
    assert fresh.total_participants == 3
    charlie_stats = UserWrappedStatistics.objects.get(wrapped=stats, user=charlie)
    assert charlie_stats.rank == 3
    assert charlie_stats.display_name == "Charlie"


def test_activity_outside_the_year_window_is_excluded():
    fixture = WrappedFixture()
    fixture.create_alice_activity()
    early = fixture.user("early@test.com")
    early_enrollment = fixture.enrollment(early, "Early", 10)
    fixture.homework_submission(
        early, early_enrollment, lecture_hours=1.0, homework_hours=1.0, submitted_at=in_2024()
    )

    stats_2025 = calculate_wrapped_statistics(year=2025, force=True)

    assert stats_2025.total_participants == 1
    assert not UserWrappedStatistics.objects.filter(wrapped=stats_2025, user=early).exists()

    stats_2024 = calculate_wrapped_statistics(year=2024, force=True)

    assert stats_2024.total_participants == 1
    assert UserWrappedStatistics.objects.get(wrapped=stats_2024, user=early).display_name == "Early"


def test_replace_user_wrapped_statistics_replaces_stale_rows():
    fixture, stats = donor_fixture()

    replace_user_wrapped_statistics(stats, [UserWrappedStatistics(user=fixture.bob)])

    users = list(
        UserWrappedStatistics.objects.filter(wrapped=stats).values_list("user_id", flat=True)
    )
    assert users == [fixture.bob.id]
    assert UserWrappedStatistics.objects.get(wrapped=stats, user=fixture.bob).wrapped == stats


def test_get_user_wrapped_returns_none_without_a_user_row():
    _, stats = donor_fixture()
    outsider = User.objects.create_user(email="outsider@test.com")

    assert get_user_wrapped(stats, outsider) is None
    assert get_user_wrapped(stats, User.objects.get(email="alice@test.com")) is not None
