import datetime

import pytest
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    PeerReview,
    ProjectSubmission,
    Submission,
    Testimonial,
    TestimonialPlacement,
    UserWrappedStatistics,
)
from community_base.coursework.testimonials import (
    publish_testimonial,
    published_testimonials,
    reorder_testimonials,
    unpublish_testimonial,
)
from community_base.coursework.wrapped import (
    calculate_wrapped_statistics,
    get_user_wrapped,
    visible_wrapped,
    wrapped_read_model,
)
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import homework as make_homework
from tests.curriculum.test_models import make_cohort, make_course

pytestmark = pytest.mark.django_db


def coursework_cohort(slug="cw-wrapped"):
    course = make_course(slug=f"{slug}-course", title="Wrapped Course")
    return make_cohort(course, slug=slug, title="Wrapped cohort")


def homework_submission(
    cohort, email, *, hours_lectures=2.0, hours_homework=3.0, faq=None, submitted_at=None
):
    user = User.objects.create_user(email=email)
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    return Submission.objects.create(
        homework=make_homework(cohort, slug=f"hw-{cohort.homeworks.count() + 1}"),
        student=user,
        submitted_at=submitted_at or timezone.now(),
        enrollment=enrollment,
        time_spent_lectures=hours_lectures,
        time_spent_homework=hours_homework,
        faq_contribution_url=faq,
        learning_in_public_links=["https://example.com/post"],
    )


def project_submission(cohort, email, *, time_spent=1.5, submitted_at=None):
    from tests.coursework.test_projects import make_project

    user = User.objects.filter(email=email).first() or User.objects.create_user(email=email)
    enrollment = Enrollment.objects.get_or_create(user=user, cohort=cohort)[0]
    return ProjectSubmission.objects.create(
        project=make_project(cohort, slug=f"final-{cohort.projects.count() + 1}"),
        student=user,
        enrollment=enrollment,
        submitted_at=submitted_at or timezone.now(),
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
        time_spent=time_spent,
        learning_in_public_links=["https://example.com/project-post"],
    )


def test_calculate_wrapped_statistics_is_idempotent_without_force():
    cohort = coursework_cohort()
    homework_submission(cohort, "wrapped1@example.com", faq="https://example.com/faq")

    first = calculate_wrapped_statistics(year=2026)
    second = calculate_wrapped_statistics(year=2026)

    assert first.pk == second.pk
    assert first.total_participants == 1
    assert UserWrappedStatistics.objects.filter(wrapped=first).count() == 1


def test_calculate_wrapped_statistics_aggregates_platform_and_users():
    cohort = coursework_cohort()
    homework_submission(cohort, "hours@example.com", hours_lectures=150.0)
    homework_submission(cohort, "hours2@example.com", hours_homework=200.0)

    stats = calculate_wrapped_statistics(year=2026)

    # 100 + 3 and 2 + 100: per-submission fields are capped at 100 hours.
    assert stats.total_hours == 205.0
    assert stats.total_participants == 2
    assert stats.total_enrollments == 2
    assert stats.leaderboard[0]["rank"] == 1
    assert stats.course_stats[0]["enrollment_count"] == 2

    hours = sorted(
        UserWrappedStatistics.objects.filter(wrapped=stats).values_list(
            "total_hours", flat=True
        )
    )
    assert hours == [102.0, 103.0]
    learner = UserWrappedStatistics.objects.filter(wrapped=stats).first()
    assert learner.learning_in_public_count == 1
    assert learner.homework_count == 1
    ranks = sorted(
        UserWrappedStatistics.objects.filter(wrapped=stats).values_list("rank", flat=True)
    )
    assert ranks == [1, 2]


def test_force_recalculate_replaces_user_rows():
    cohort = coursework_cohort()
    homework_submission(cohort, "replace@example.com")

    stats = calculate_wrapped_statistics(year=2026)
    calculate_wrapped_statistics(year=2026, force=True)

    assert UserWrappedStatistics.objects.filter(wrapped=stats).count() == 1


def test_peer_reviews_given_counts_submitted_reviews_in_window():
    cohort = coursework_cohort()
    reviewer_submission = project_submission(cohort, "reviewer@example.com")
    target_submission = project_submission(cohort, "target@example.com")
    PeerReview.objects.create(
        submission_under_evaluation=target_submission,
        reviewer=reviewer_submission,
        submitted_at=timezone.now(),
    )
    PeerReview.objects.create(
        submission_under_evaluation=target_submission,
        reviewer=reviewer_submission,
    )

    stats = calculate_wrapped_statistics(year=2026)

    reviewer_stats = get_user_wrapped(stats, reviewer_submission.student)
    assert reviewer_stats.peer_reviews_given == 1


def test_visible_wrapped_read_model_hides_unpublished_years():
    cohort = coursework_cohort()
    year_start = datetime.datetime(2030, 6, 1, tzinfo=datetime.UTC)
    homework_submission(cohort, "visible@example.com", submitted_at=year_start)
    hidden = calculate_wrapped_statistics(year=2030)
    hidden.is_visible = True
    hidden.save()
    calculate_wrapped_statistics(year=2031)

    assert [row.year for row in visible_wrapped()] == [2030]

    reader = User.objects.get(email="visible@example.com")
    read_model = wrapped_read_model(hidden, reader)
    assert read_model.user_stats.display_name or read_model.user_stats.rank is not None
    assert read_model.leaderboard == hidden.leaderboard


def test_testimonial_publish_reorder_and_unpublish():
    homepage = TestimonialPlacement.HOMEPAGE
    first = Testimonial.objects.create(placement=homepage, name="A", quote="q", published=False)
    second = Testimonial.objects.create(placement=homepage, name="B", quote="q", published=False)

    assert published_testimonials(homepage) == []

    publish_testimonial(first)
    publish_testimonial(second)
    assert published_testimonials(homepage) == [first, second]

    reorder_testimonials(homepage, [second.id, first.id])
    assert list(Testimonial.objects.filter(placement=homepage).order_by("position")) == [
        second,
        first,
    ]

    unpublish_testimonial(second)
    assert published_testimonials(homepage) == [first]

    with pytest.raises(ValueError):
        reorder_testimonials(homepage, [999999])
