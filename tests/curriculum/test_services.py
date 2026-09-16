import datetime

import pytest
from django.utils import timezone

from community_base.curriculum.models import CohortModule, Enrollment, UnitProgress
from community_base.curriculum.services import (
    ChecklistItemState,
    DripDecision,
    completed_unit_ids,
    decide_unit_drip,
    ensure_enrollment,
    get_all_units_ordered,
    get_checklist_items,
    get_checklist_state,
    get_next_unit,
    get_next_unit_for_user,
    get_prev_unit,
    is_completed,
    is_enrolled,
    mark_completed,
    unenroll,
    unmark_completed,
)
from community_base.events.models import Host
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


def user_with_course(django_user_model, username="learner"):
    user = django_user_model.objects.create_user(email=f"{username}@example.com")
    course = make_course()
    cohort = make_cohort(course)
    module = make_module(course)
    return user, course, cohort, module


@pytest.mark.django_db
class TestEnrollment:
    def test_ensure_is_idempotent(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)

        enrollment, created = ensure_enrollment(user, cohort)
        assert created is True

        again, created_again = ensure_enrollment(user, cohort)
        assert created_again is False
        assert again.pk == enrollment.pk

    def test_ensure_anonymous_is_noop(self):
        enrollment, created = ensure_enrollment(None, None)

        assert enrollment is None
        assert created is False

    def test_unenroll_then_reenroll(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        ensure_enrollment(user, cohort)

        assert unenroll(user, cohort) is True
        assert is_enrolled(user, cohort) is False

        enrollment, created = ensure_enrollment(user, cohort)
        assert created is True
        assert Enrollment.objects.filter(user=user, cohort=cohort).count() == 2

    def test_unenroll_without_enrollment_is_false(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)

        assert unenroll(user, cohort) is False


@pytest.mark.django_db
class TestProgress:
    def test_mark_completed_is_idempotent(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        unit = make_unit(module)

        first = mark_completed(user, unit, cohort=cohort)
        second = mark_completed(user, unit, cohort=cohort)

        assert first.completed_at is not None
        assert second.pk == first.pk
        assert is_completed(user, unit) is True

    def test_mark_completed_auto_enrolls_in_given_cohort(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        unit = make_unit(module)

        mark_completed(user, unit, cohort=cohort)

        assert is_enrolled(user, cohort) is True

    def test_mark_completed_without_cohort_auto_enrolls_in_self_paced(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        unit = make_unit(module)

        mark_completed(user, unit)

        self_paced = course.cohorts.get(mode="self_paced")
        assert is_enrolled(user, self_paced) is True

    def test_unmark_completed_deletes_row(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        unit = make_unit(module)
        mark_completed(user, unit, cohort=cohort)

        assert unmark_completed(user, unit) is True
        assert is_completed(user, unit) is False
        assert UnitProgress.objects.filter(user=user, unit=unit).count() == 0

    def test_anonymous_progress_is_rejected(self):
        course = make_course()
        unit = make_unit(make_module(course))

        assert mark_completed(None, unit) is None
        assert is_completed(None, unit) is False
        assert unmark_completed(None, unit) is False

    def test_completed_unit_ids_batched(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        first = make_unit(module, slug="one", title="One")
        second = make_unit(module, slug="two", title="Two")
        mark_completed(user, first, cohort=cohort)

        assert completed_unit_ids(user, [first, second]) == {first.pk}
        assert completed_unit_ids(None, [first]) == set()
        assert completed_unit_ids(user, []) == set()


@pytest.mark.django_db
class TestDrip:
    def drip_unit(self, module, **values):
        values.setdefault("slug", "dripped")
        values.setdefault("title", "Dripped")
        values.setdefault("available_after_days", 7)
        return make_unit(module, **values)

    def test_unit_without_drip_is_never_locked(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        unit = make_unit(module)

        assert decide_unit_drip(user, unit, cohort) == DripDecision(is_locked=False)

    def test_self_paced_cohort_never_locks(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        cohort.mode = "self_paced"
        cohort.start_date = None
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)

        assert decide_unit_drip(user, unit, cohort).is_locked is False

    def test_locked_before_available_date(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        cohort.start_date = datetime.date(2026, 9, 7)
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)
        today = datetime.date(2026, 9, 10)

        decision = decide_unit_drip(user, unit, cohort, today=today)

        assert decision.is_locked is True
        assert decision.available_date == datetime.date(2026, 9, 14)

    def test_open_on_available_date(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        cohort.start_date = datetime.date(2026, 9, 7)
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)

        decision = decide_unit_drip(user, unit, cohort, today=datetime.date(2026, 9, 14))

        assert decision.is_locked is False

    def test_not_enrolled_is_never_locked(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        cohort.start_date = timezone.now().date()
        cohort.save()
        unit = self.drip_unit(module)

        assert decide_unit_drip(user, unit, cohort).is_locked is False

    def test_course_started_today_with_seven_day_drip_is_locked(self, django_user_model):
        user, course, cohort, module = user_with_course(django_user_model)
        cohort.start_date = timezone.now().date()
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)

        assert decide_unit_drip(user, unit, cohort).is_locked is True

    def test_drip_falls_back_to_module_then_parent_module_offset(self, django_user_model):
        user, course, cohort, _module = user_with_course(django_user_model)
        cohort.start_date = datetime.date(2026, 9, 7)
        cohort.save()
        ensure_enrollment(user, cohort)
        week = make_module(course, slug="week-1", title="Week 1", available_after_days=7)
        topic = make_module(course, slug="topic", title="Topic", parent=week)
        unit = make_unit(topic)

        decision = decide_unit_drip(user, unit, cohort, today=datetime.date(2026, 9, 10))

        assert decision.is_locked is True
        assert decision.available_date == datetime.date(2026, 9, 14)


@pytest.mark.django_db
class TestReadingOrder:
    def ordered_course(self):
        course = make_course()
        first = make_module(course, slug="m1", title="M1", sort_order=1)
        second = make_module(course, slug="m2", title="M2", sort_order=2)
        u1 = make_unit(first, slug="u1", title="U1", sort_order=1)
        u2 = make_unit(first, slug="u2", title="U2", sort_order=2)
        u3 = make_unit(second, slug="u3", title="U3", sort_order=1)
        return course, [u1, u2, u3]

    def test_reading_order_spans_modules(self):
        course, units = self.ordered_course()

        assert get_all_units_ordered(course) == units

    def test_reading_order_is_depth_first_through_submodules(self):
        course = make_course()
        week = make_module(course, slug="week-1", title="Week 1", sort_order=1)
        topic_a = make_module(course, slug="topic-a", title="Topic A", parent=week, sort_order=1)
        topic_b = make_module(course, slug="topic-b", title="Topic B", parent=week, sort_order=2)
        u_a1 = make_unit(topic_a, slug="a1", title="A1", sort_order=1)
        u_a2 = make_unit(topic_a, slug="a2", title="A2", sort_order=2)
        u_b1 = make_unit(topic_b, slug="b1", title="B1", sort_order=1)

        assert get_all_units_ordered(course) == [u_a1, u_a2, u_b1]

    def test_next_and_prev_walk_reading_order(self):
        course, (u1, u2, u3) = self.ordered_course()

        assert get_next_unit(course, u1) == u2
        assert get_next_unit(course, u2) == u3
        assert get_next_unit(course, u3) is None
        assert get_prev_unit(course, u3) == u2
        assert get_prev_unit(course, u1) is None

    def test_next_unit_for_user_skips_completed(self, django_user_model):
        user, units = self.ordered_course_user(django_user_model)
        u1, u2, u3 = units
        mark_completed(user, u1)

        assert get_next_unit_for_user(u1.module.course, user) == u2

    def test_next_unit_for_user_returns_none_when_all_complete(self, django_user_model):
        user, units = self.ordered_course_user(django_user_model)
        for unit in units:
            mark_completed(user, unit)

        assert get_next_unit_for_user(units[0].module.course, user) is None

    def test_next_unit_for_anonymous_is_none(self):
        course, units = self.ordered_course()

        assert get_next_unit_for_user(course, None) is None

    def ordered_course_user(self, django_user_model, username="walker"):
        user = django_user_model.objects.create_user(email=f"{username}@example.com")
        course, units = self.ordered_course()
        return user, units


@pytest.mark.django_db
def test_course_counters(django_user_model):
    user = django_user_model.objects.create_user(email="cnt@example.com")
    course = make_course()
    module = make_module(course)
    make_unit(module)
    make_unit(module, slug="two", title="Two")

    assert course.total_units() == 2
    assert course.completed_units(user) == 0
    mark_completed(user, module.units.first())
    assert course.completed_units(user) == 1
    assert course.completed_units(None) == 0


@pytest.mark.django_db
def test_course_counters_exclude_bonus_but_include_events():
    user_model_unit = make_unit  # local alias, no user needed for this assertion
    course = make_course()
    module = make_module(course)
    user_model_unit(module, slug="lesson", title="Lesson")
    user_model_unit(module, slug="event", title="Event", kind="event")
    user_model_unit(module, slug="bonus", title="Bonus", is_bonus=True)
    bonus_module = make_module(course, slug="bonus-module", title="Bonus module", is_bonus=True)
    user_model_unit(bonus_module, slug="in-bonus-module", title="In bonus module")

    # lesson + event count; the direct bonus unit and everything under the bonus
    # module are excluded from the denominator.
    assert course.total_units() == 2


@pytest.mark.django_db
def test_course_counters_exclude_checklist_items_regardless_of_is_bonus():
    course = make_course()
    module = make_module(course)
    make_unit(module, slug="lesson", title="Lesson")
    make_unit(module, slug="required-checklist", title="Read the docs", kind="checklist_item")
    make_unit(
        module,
        slug="optional-checklist",
        title="Optional setup",
        kind="checklist_item",
        is_bonus=True,
    )

    # Only the lesson counts: checklist items never enter the course-progress
    # denominator, whether marked required (is_bonus=False) or optional (is_bonus=True).
    assert course.total_units() == 1
    assert course._countable_units().count() == 1


@pytest.mark.django_db
def test_course_get_syllabus_orders_cohorts_and_uses_placements():
    course = make_course()
    late = make_cohort(course, slug="2027", title="2027")
    late.start_date = datetime.date(2027, 1, 1)
    late.save()
    early = make_cohort(course, slug="2026", title="2026")
    early.start_date = datetime.date(2026, 1, 1)
    early.save()
    late_module = make_module(course, slug="late-module", title="Late", sort_order=0)
    make_module(course, slug="early-module", title="Early", sort_order=1)
    CohortModule.objects.create(cohort=late, module=late_module, sort_order=0)

    cohorts = list(course.get_syllabus())

    assert [cohort.slug for cohort in cohorts] == ["2026", "2027"]
    # `early` has no placements: it falls back to the full course tree (both modules).
    assert [module.slug for module in cohorts[0].syllabus_modules] == [
        "late-module",
        "early-module",
    ]
    # `late` has an explicit placement: only the module it selected.
    assert [module.slug for module in cohorts[1].syllabus_modules] == ["late-module"]


@pytest.mark.django_db
def test_instructor_related_courses():
    course = make_course()
    host = Host.objects.create(name="Instructor Host", slug="instructor-host")

    course.instructors.add(host, through_defaults={"position": 0})

    assert list(host.courses.all()) == [course]


@pytest.mark.django_db
class TestChecklist:
    def pre_work_module(self):
        course = make_course()
        module = make_module(course, slug="before-you-start", title="Before you start")
        read_docs = make_unit(
            module, slug="read-docs", title="Read the docs", kind="checklist_item"
        )
        install_tools = make_unit(
            module,
            slug="install-tools",
            title="Install tools",
            kind="checklist_item",
            sort_order=1,
        )
        optional_setup = make_unit(
            module,
            slug="optional-setup",
            title="Optional setup",
            kind="checklist_item",
            is_bonus=True,
            sort_order=2,
        )
        # A lesson unit in the same module must never show up as a checklist item.
        make_unit(module, slug="intro-lesson", title="Intro lesson")
        return module, read_docs, install_tools, optional_setup

    def test_get_checklist_items_excludes_other_kinds_and_is_ordered(self):
        module, read_docs, install_tools, optional_setup = self.pre_work_module()

        assert get_checklist_items(module) == [read_docs, install_tools, optional_setup]

    def test_get_checklist_state_reflects_required_and_completion(self, django_user_model):
        module, read_docs, install_tools, optional_setup = self.pre_work_module()
        user = django_user_model.objects.create_user(email="checklist@example.com")

        state = get_checklist_state(user, module)

        assert state == [
            ChecklistItemState(unit=read_docs, is_required=True, is_completed=False),
            ChecklistItemState(unit=install_tools, is_required=True, is_completed=False),
            ChecklistItemState(unit=optional_setup, is_required=False, is_completed=False),
        ]

        mark_completed(user, read_docs)
        unmark_completed(user, install_tools)  # already incomplete; asserts it stays a no-op

        state = get_checklist_state(user, module)
        assert state[0] == ChecklistItemState(unit=read_docs, is_required=True, is_completed=True)
        assert state[1].is_completed is False
        assert state[2].is_completed is False

    def test_get_checklist_state_anonymous_user_all_incomplete(self):
        module, read_docs, install_tools, optional_setup = self.pre_work_module()

        state = get_checklist_state(None, module)

        assert [item.is_completed for item in state] == [False, False, False]

    def test_checklist_items_use_the_shared_unit_progress_toggle(self, django_user_model):
        """Reuses mark_completed/unmark_completed/is_completed -- no parallel tracking model."""

        module, read_docs, _install_tools, _optional_setup = self.pre_work_module()
        user = django_user_model.objects.create_user(email="toggle@example.com")

        assert is_completed(user, read_docs) is False
        mark_completed(user, read_docs)
        assert is_completed(user, read_docs) is True
        assert UnitProgress.objects.filter(user=user, unit=read_docs).exists()

        assert unmark_completed(user, read_docs) is True
        assert is_completed(user, read_docs) is False
