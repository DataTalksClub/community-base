import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from community_base.accounts.models import User
from community_base.curriculum.models import (
    Certificate,
    Cohort,
    Course,
    CourseInstructor,
    Enrollment,
    Module,
    Unit,
    UnitProgress,
)
from community_base.events.models import Host

pytestmark = pytest.mark.django_db


def make_course(**values):
    values.setdefault("slug", "test-course")
    values.setdefault("title", "Test Course")
    return Course.objects.create(**values)


def make_cohort(course, **values):
    values.setdefault("slug", "2026")
    values.setdefault("title", "2026 cohort")
    return Cohort.objects.create(course=course, **values)


def make_module(cohort, **values):
    values.setdefault("slug", "intro")
    values.setdefault("title", "Intro")
    return Module.objects.create(cohort=cohort, **values)


def make_unit(module, **values):
    values.setdefault("slug", "welcome")
    values.setdefault("title", "Welcome")
    return Unit.objects.create(module=module, **values)


def test_course_renders_description_markdown():
    course = make_course(description="# Test Course\n\nLearn **things**.")

    assert "<h1>" not in course.description_html
    assert "<strong>things</strong>" in course.description_html


def test_course_strips_leading_h1_matching_title():
    course = make_course(description="# Test Course\n\nBody text.")

    assert "<h1>" not in course.description_html
    assert "Body text." in course.description_html


def test_course_keeps_leading_h1_with_different_text():
    course = make_course(description="# Welcome aboard\n\nBody text.")

    assert "<h1>" in course.description_html


def test_course_description_html_is_sanitized():
    course = make_course(description="Hello <script>alert(1)</script> world.")

    assert "<script>" not in course.description_html
    assert "world" in course.description_html


def test_module_and_unit_render_markdown_on_save():
    cohort = make_cohort(make_course())
    module = make_module(cohort, overview="# Intro\n\nOverview *text*.")
    unit = make_unit(module, body="# Welcome\n\nBody text.", homework="Do the **task**.")

    assert "Overview <em>text</em>." in module.overview_html
    assert "Body text." in unit.body_html
    assert "<strong>task</strong>" in unit.homework_html


def test_module_save_with_update_fields_rerenders_overview_html():
    cohort = make_cohort(make_course())
    module = make_module(cohort, overview="First draft")

    module.overview = "Second *draft*"
    module.save(update_fields=["overview"])

    module.refresh_from_db()
    assert "Second <em>draft</em>" in module.overview_html


def test_unit_save_with_update_fields_rerenders_body_html():
    cohort = make_cohort(make_course())
    module = make_module(cohort)
    unit = make_unit(module, body="First draft")

    unit.body = "Second *draft*"
    unit.save(update_fields=["body"])

    unit.refresh_from_db()
    assert "Second <em>draft</em>" in unit.body_html


def test_provenance_must_be_complete():
    course = make_course(source_content_id="3f2b4a1e-0000-4000-8000-000000000001")

    with pytest.raises(ValidationError):
        course.full_clean()


def test_provenance_all_fields_pass_clean():
    course = make_course()
    course.source_content_id = "3f2b4a1e-0000-4000-8000-000000000001"
    course.source_path = "courses/test-course/course.yaml"
    course.source_commit_sha = "a" * 40
    course.source_checksum = "b" * 64

    course.full_clean()


def test_provenance_rejects_invalid_commit_shape():
    course = make_course(source_commit_sha="not-a-sha")

    with pytest.raises(ValidationError):
        course.full_clean()


def test_cohort_slug_unique_per_course():
    course = make_course()
    make_cohort(course, slug="2026")

    with pytest.raises(IntegrityError), transaction.atomic():
        Cohort(course=course, slug="2026", title="dup").save()


def test_course_allows_one_self_paced_cohort():
    course = make_course()
    make_cohort(course, slug="self-paced", mode="self_paced", title="Self-paced")

    with pytest.raises(IntegrityError), transaction.atomic():
        Cohort(course=course, slug="self-paced-2", mode="self_paced", title="Dup").save()


def test_cohort_rejects_end_before_start():
    course = make_course()
    cohort = Cohort(
        course=course,
        slug="2026",
        title="2026",
        start_date=datetime.date(2026, 5, 1),
        end_date=datetime.date(2026, 4, 1),
    )

    with pytest.raises(ValidationError):
        cohort.full_clean()


def test_cohort_capacity_properties():
    course = make_course()
    cohort = make_cohort(course, max_participants=2)

    assert cohort.is_full is False
    assert cohort.spots_remaining == 2

    user = User.objects.create_user(email="a@example.com")
    Enrollment.objects.create(user=user, cohort=cohort)
    assert cohort.enrollment_count == 1
    assert cohort.spots_remaining == 1


def test_enrollment_count_ignores_unenrolled():
    course = make_course()
    cohort = make_cohort(course)
    user = User.objects.create_user(email="b@example.com")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)

    enrollment.unenrolled_at = enrollment.enrolled_at
    enrollment.save(update_fields=["unenrolled_at"])

    assert cohort.enrollment_count == 0
    assert enrollment.is_active is False


def test_unit_effective_required_level_chain():
    course = make_course(required_level=10, default_unit_required_level=5)
    cohort = make_cohort(course)
    module = make_module(cohort)
    inherited = make_unit(module)
    overridden = make_unit(module, slug="overridden", title="Overridden", required_level=30)

    assert inherited.effective_required_level == 5
    assert overridden.effective_required_level == 30


def test_unit_effective_required_level_falls_back_to_course_level():
    course = make_course(required_level=20)
    module = make_module(make_cohort(course))
    unit = make_unit(module)

    assert unit.effective_required_level == 20


def test_course_instructor_ordering():
    course = make_course()
    second = Host.objects.create(name="Second", slug="second")
    first = Host.objects.create(name="First", slug="first")
    CourseInstructor.objects.create(course=course, host=second, position=2)
    CourseInstructor.objects.create(course=course, host=first, position=1)

    assert course.ordered_instructors == [first, second]
    assert course.primary_instructor == first


def test_certificate_is_one_per_enrollment():
    course = make_course()
    cohort = make_cohort(course)
    user = User.objects.create_user(email="c@example.com")
    enrollment = Enrollment.objects.create(user=user, cohort=cohort)
    Certificate.objects.create(enrollment=enrollment, url="https://example.com/cert.pdf")

    assert enrollment.certificate.url == "https://example.com/cert.pdf"
    assert enrollment.certificate.get_absolute_url().startswith("/certificates/")


def test_unit_progress_unique_per_user_and_unit():
    course = make_course()
    module = make_module(make_cohort(course))
    unit = make_unit(module)
    user = User.objects.create_user(email="d@example.com")
    UnitProgress.objects.create(user=user, unit=unit)

    with pytest.raises(IntegrityError), transaction.atomic():
        UnitProgress(user=user, unit=unit).save()
