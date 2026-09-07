import datetime

import pytest
from django.utils import timezone

from community_base.curriculum.models import Enrollment, UnitProgress
from community_base.curriculum.services import (
    DripDecision,
    completed_unit_ids,
    decide_unit_drip,
    ensure_enrollment,
    get_all_units_ordered,
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
    module = make_module(cohort)
    return user, course, module


@pytest.mark.django_db
class TestEnrollment:
    def test_ensure_is_idempotent(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort

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
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort
        ensure_enrollment(user, cohort)

        assert unenroll(user, cohort) is True
        assert is_enrolled(user, cohort) is False

        enrollment, created = ensure_enrollment(user, cohort)
        assert created is True
        assert Enrollment.objects.filter(user=user, cohort=cohort).count() == 2

    def test_unenroll_without_enrollment_is_false(self, django_user_model):
        user, course, module = user_with_course(django_user_model)

        assert unenroll(user, module.cohort) is False


@pytest.mark.django_db
class TestProgress:
    def test_mark_completed_is_idempotent(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        unit = make_unit(module)

        first = mark_completed(user, unit)
        second = mark_completed(user, unit)

        assert first.completed_at is not None
        assert second.pk == first.pk
        assert is_completed(user, unit) is True

    def test_mark_completed_auto_enrolls_in_cohort(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        unit = make_unit(module)

        mark_completed(user, unit)

        assert is_enrolled(user, module.cohort) is True

    def test_unmark_completed_deletes_row(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        unit = make_unit(module)
        mark_completed(user, unit)

        assert unmark_completed(user, unit) is True
        assert is_completed(user, unit) is False
        assert UnitProgress.objects.filter(user=user, unit=unit).count() == 0

    def test_anonymous_progress_is_rejected(self):
        course = make_course()
        unit = make_unit(make_module(make_cohort(course)))

        assert mark_completed(None, unit) is None
        assert is_completed(None, unit) is False
        assert unmark_completed(None, unit) is False

    def test_completed_unit_ids_batched(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        first = make_unit(module, slug="one", title="One")
        second = make_unit(module, slug="two", title="Two")
        mark_completed(user, first)

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
        user, course, module = user_with_course(django_user_model)
        unit = make_unit(module)

        assert decide_unit_drip(user, unit) == DripDecision(is_locked=False)

    def test_self_paced_cohort_never_locks(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort
        cohort.mode = "self_paced"
        cohort.start_date = None
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)

        assert decide_unit_drip(user, unit).is_locked is False

    def test_locked_before_available_date(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort
        cohort.start_date = datetime.date(2026, 9, 7)
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)
        today = datetime.date(2026, 9, 10)

        decision = decide_unit_drip(user, unit, today=today)

        assert decision.is_locked is True
        assert decision.available_date == datetime.date(2026, 9, 14)

    def test_open_on_available_date(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort
        cohort.start_date = datetime.date(2026, 9, 7)
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)

        decision = decide_unit_drip(user, unit, today=datetime.date(2026, 9, 14))

        assert decision.is_locked is False

    def test_not_enrolled_is_never_locked(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort
        cohort.start_date = timezone.now().date()
        cohort.save()
        unit = self.drip_unit(module)

        assert decide_unit_drip(user, unit).is_locked is False

    def test_course_started_today_with_seven_day_drip_is_locked(self, django_user_model):
        user, course, module = user_with_course(django_user_model)
        cohort = module.cohort
        cohort.start_date = timezone.now().date()
        cohort.save()
        ensure_enrollment(user, cohort)
        unit = self.drip_unit(module)

        assert decide_unit_drip(user, unit).is_locked is True


@pytest.mark.django_db
class TestReadingOrder:
    def ordered_course(self):
        course = make_course()
        cohort = make_cohort(course)
        first = make_module(cohort, slug="m1", title="M1", sort_order=1)
        second = make_module(cohort, slug="m2", title="M2", sort_order=2)
        u1 = make_unit(first, slug="u1", title="U1", sort_order=1)
        u2 = make_unit(first, slug="u2", title="U2", sort_order=2)
        u3 = make_unit(second, slug="u3", title="U3", sort_order=1)
        return course, [u1, u2, u3]

    def test_reading_order_spans_modules(self):
        course, units = self.ordered_course()

        assert get_all_units_ordered(course) == units

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

        assert get_next_unit_for_user(u1.module.cohort.course, user) == u2

    def test_next_unit_for_user_returns_none_when_all_complete(self, django_user_model):
        user, units = self.ordered_course_user(django_user_model)
        for unit in units:
            mark_completed(user, unit)

        assert get_next_unit_for_user(units[0].module.cohort.course, user) is None

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
    cohort = make_cohort(course)
    module = make_module(cohort)
    make_unit(module)
    make_unit(module, slug="two", title="Two")

    assert course.total_units() == 2
    assert course.completed_units(user) == 0
    mark_completed(user, module.units.first())
    assert course.completed_units(user) == 1
    assert course.completed_units(None) == 0


@pytest.mark.django_db
def test_course_get_syllabus_orders_cohorts_and_modules():
    course = make_course()
    late = make_cohort(course, slug="2027", title="2027")
    late.start_date = datetime.date(2027, 1, 1)
    late.save()
    early = make_cohort(course, slug="2026", title="2026")
    early.start_date = datetime.date(2026, 1, 1)
    early.save()
    make_module(late, slug="late-module", title="Late", sort_order=0)
    make_module(early, slug="early-module", title="Early", sort_order=1)

    cohorts = list(course.get_syllabus())

    assert [cohort.slug for cohort in cohorts] == ["2026", "2027"]
    assert [module.slug for module in cohorts[1].modules.all()] == ["late-module"]


@pytest.mark.django_db
def test_instructor_related_courses():
    course = make_course()
    host = Host.objects.create(name="Instructor Host", slug="instructor-host")

    course.instructors.add(host, through_defaults={"position": 0})

    assert list(host.courses.all()) == [course]
