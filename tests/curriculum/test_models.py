import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from community_base.accounts.models import User
from community_base.curriculum.models import (
    Certificate,
    Cohort,
    CohortModule,
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
    values.setdefault("status", "published")
    return Course.objects.create(**values)


def make_cohort(course, **values):
    values.setdefault("slug", "2026")
    values.setdefault("title", "2026 cohort")
    return Cohort.objects.create(course=course, **values)


def make_module(course, **values):
    values.setdefault("slug", "intro")
    values.setdefault("title", "Intro")
    return Module.objects.create(course=course, **values)


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
    course = make_course()
    module = make_module(course, overview="# Intro\n\nOverview *text*.")
    unit = make_unit(module, body="# Welcome\n\nBody text.", homework="Do the **task**.")

    assert "Overview <em>text</em>." in module.overview_html
    assert "Body text." in unit.body_html
    assert "<strong>task</strong>" in unit.homework_html


def test_module_save_with_update_fields_rerenders_overview_html():
    course = make_course()
    module = make_module(course, overview="First draft")

    module.overview = "Second *draft*"
    module.save(update_fields=["overview"])

    module.refresh_from_db()
    assert "Second <em>draft</em>" in module.overview_html


def test_unit_save_with_update_fields_rerenders_body_html():
    course = make_course()
    module = make_module(course)
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
    module = make_module(course)
    inherited = make_unit(module)
    overridden = make_unit(module, slug="overridden", title="Overridden", required_level=30)

    assert inherited.effective_required_level == 5
    assert overridden.effective_required_level == 30


def test_unit_effective_required_level_falls_back_to_course_level():
    course = make_course(required_level=20)
    module = make_module(course)
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
    module = make_module(course)
    unit = make_unit(module)
    user = User.objects.create_user(email="d@example.com")
    UnitProgress.objects.create(user=user, unit=unit)

    with pytest.raises(IntegrityError), transaction.atomic():
        UnitProgress(user=user, unit=unit).save()


# --- nesting (community-base#252) ---


def test_module_parent_makes_a_submodule():
    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1")
    child = make_module(course, slug="topic-a", title="Topic A", parent=parent)

    assert child.parent_id == parent.pk
    assert list(parent.children.all()) == [child]


def test_module_rejects_three_levels_deep():
    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1")
    child = make_module(course, slug="topic-a", title="Topic A", parent=parent)
    grandchild = Module(course=course, slug="too-deep", title="Too deep", parent=child)

    with pytest.raises(ValidationError):
        grandchild.full_clean()


def test_module_rejects_self_parent():
    course = make_course()
    module = make_module(course)
    module.parent = module

    with pytest.raises(ValidationError):
        module.full_clean()


def test_module_rejects_parent_from_another_course():
    other_course = make_course(slug="other-course")
    other_parent = make_module(other_course, slug="week-1", title="Week 1")
    course = make_course()

    child = Module(course=course, slug="topic-a", title="Topic A", parent=other_parent)
    with pytest.raises(ValidationError):
        child.full_clean()


def test_module_with_children_cannot_also_have_direct_units():
    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1")
    make_module(course, slug="topic-a", title="Topic A", parent=parent)
    # Bypass Unit.clean()'s own guard to construct the invalid state directly,
    # so Module.clean()'s defensive check (both children and units present) is
    # what is actually under test here.
    Unit.objects.create(module=parent, slug="stray", title="Stray")

    with pytest.raises(ValidationError):
        parent.full_clean()


def test_parent_with_units_cannot_also_have_children():
    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1")
    make_unit(parent)

    child = Module(course=course, slug="topic-a", title="Topic A", parent=parent)
    with pytest.raises(ValidationError):
        child.full_clean()


def test_unit_cannot_be_added_to_a_module_with_children():
    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1")
    make_module(course, slug="topic-a", title="Topic A", parent=parent)

    unit = Unit(module=parent, slug="stray", title="Stray")
    with pytest.raises(ValidationError):
        unit.full_clean()


def test_two_submodules_may_each_contain_a_unit_slugged_the_same():
    """The exact collision case the flattened site content hit 26 times."""

    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1")
    sub_a = make_module(course, slug="topic-a", title="Topic A", parent=parent)
    sub_b = make_module(course, slug="topic-b", title="Topic B", parent=parent)

    unit_a = make_unit(sub_a, slug="section-overview", title="Overview")
    unit_b = make_unit(sub_b, slug="section-overview", title="Overview")

    assert unit_a.pk != unit_b.pk
    assert Unit.objects.filter(slug="section-overview").count() == 2


def test_module_slug_unique_per_parent_not_per_course():
    course = make_course()
    parent_a = make_module(course, slug="parent-a", title="Parent A")
    parent_b = make_module(course, slug="parent-b", title="Parent B")

    make_module(course, slug="overview", title="Overview", parent=parent_a)
    make_module(course, slug="overview", title="Overview", parent=parent_b)

    assert Module.objects.filter(slug="overview").count() == 2


def test_module_is_bonus_defaults_false_and_cascades_to_units():
    course = make_course()
    module = make_module(course)
    unit = make_unit(module)

    assert module.is_bonus is False
    assert unit.effective_is_bonus is False

    module.is_bonus = True
    module.save()
    unit.refresh_from_db()
    assert unit.effective_is_bonus is True


def test_unit_kind_defaults_to_lesson():
    course = make_course()
    module = make_module(course)
    unit = make_unit(module)

    assert unit.kind == "lesson"


def test_unit_kind_event_with_session_position():
    course = make_course()
    module = make_module(course)
    unit = make_unit(module, kind="event", session_position=4)

    assert unit.kind == "event"
    assert unit.session_position == 4


def test_unit_kind_checklist_item():
    course = make_course()
    module = make_module(course)
    unit = make_unit(module, kind="checklist_item")

    assert unit.kind == "checklist_item"


def test_unit_effective_available_after_days_cascade():
    course = make_course()
    parent = make_module(course, slug="week-1", title="Week 1", available_after_days=21)
    child = make_module(course, slug="topic-a", title="Topic A", parent=parent)
    inherited = make_unit(child)
    overridden = make_unit(child, slug="override", title="Override", available_after_days=1)

    assert inherited.effective_available_after_days == 21
    assert overridden.effective_available_after_days == 1


def test_cohort_module_placement_targets_only_top_level_modules():
    course = make_course()
    cohort = make_cohort(course)
    parent = make_module(course, slug="week-1", title="Week 1")
    child = make_module(course, slug="topic-a", title="Topic A", parent=parent)

    placement = CohortModule(cohort=cohort, module=child, sort_order=0)
    with pytest.raises(ValidationError):
        placement.full_clean()


def test_cohort_effective_modules_defaults_to_full_course_tree():
    course = make_course()
    cohort = make_cohort(course)
    first = make_module(course, slug="a", title="A", sort_order=0)
    second = make_module(course, slug="b", title="B", sort_order=1)

    assert list(cohort.effective_modules()) == [first, second]


def test_cohort_effective_modules_uses_placements_when_present():
    """Two cohorts of the same course each select a different alternative-treatment module.

    Proves per-cohort placement is enough for DataTalks.Club's real case: cohorts of one
    course genuinely differ in content, not just ordering, because both variants live on
    the shared course and each cohort's placement selects one.
    """

    course = make_course()
    old_treatment = make_module(course, slug="tooling-2025", title="Tooling (2025 edition)")
    new_treatment = make_module(course, slug="tooling-2026", title="Tooling (2026 edition)")
    make_unit(old_treatment, slug="setup", title="Setup (old)")
    make_unit(new_treatment, slug="setup", title="Setup (new)")

    cohort_2025 = make_cohort(course, slug="2025", title="2025 cohort")
    cohort_2026 = make_cohort(course, slug="2026", title="2026 cohort")
    CohortModule.objects.create(cohort=cohort_2025, module=old_treatment, sort_order=0)
    CohortModule.objects.create(cohort=cohort_2026, module=new_treatment, sort_order=0)

    assert list(cohort_2025.effective_modules()) == [old_treatment]
    assert list(cohort_2026.effective_modules()) == [new_treatment]
    # Both variants sync/persist cleanly on the shared course; nothing about placing one
    # in a cohort disturbs the other.
    assert Module.objects.filter(course=course, slug__startswith="tooling-").count() == 2
