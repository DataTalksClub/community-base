import pytest
from django.test import override_settings

from community_base.curriculum.access import can_access, gated_reason, purchase_grants
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

_HOOK_CALLS = []


def granted(user, course):
    return True


def recording_hook(user, course):
    _HOOK_CALLS.append(course)
    return True


def open_policy_settings(hook):
    return {
        "ACCESS_POLICY": "community_base.kernel.access.OpenPolicy",
        "COURSE_ACCESS_GRANTS": hook,
    }


def paid_course(**values):
    values.setdefault("slug", "paid-course")
    values.setdefault("title", "Paid")
    values.setdefault("required_level", 10)
    return make_course(**values)


def paid_unit(**unit_values):
    course = paid_course()
    module = make_module(make_cohort(course))
    return make_unit(module, **unit_values)


@pytest.mark.django_db
class TestCourseAccess:
    def test_open_course_is_public(self):
        assert can_access(None, make_course()) is True

    def test_paid_course_denied_for_anonymous(self):
        course = paid_course()

        assert can_access(None, course) is False
        assert gated_reason(None, course) == "authentication_required"

    def test_paid_course_denied_for_authenticated_user(self, django_user_model):
        user = django_user_model.objects.create_user(email="m@example.com")

        course = paid_course()

        assert can_access(user, course) is False
        assert gated_reason(user, course) == "insufficient_level"

    @override_settings()
    def test_purchase_hook_grants_course_access(self, django_user_model, settings):
        settings.COMMUNITY_BASE = open_policy_settings("tests.curriculum.test_access.granted")
        user = django_user_model.objects.create_user(email="g@example.com")
        course = paid_course()

        assert can_access(user, course) is True
        assert gated_reason(user, course) == ""

    def test_purchase_hook_receives_the_course(self, django_user_model, settings):
        settings.COMMUNITY_BASE = open_policy_settings(
            "tests.curriculum.test_access.recording_hook"
        )
        _HOOK_CALLS.clear()
        user = django_user_model.objects.create_user(email="h@example.com")
        course = paid_course()

        assert purchase_grants(user, course) is True
        assert _HOOK_CALLS == [course]

    def test_purchase_grants_without_hook_is_false(self, django_user_model):
        user = django_user_model.objects.create_user(email="y@example.com")

        assert purchase_grants(user, paid_course()) is False


@pytest.mark.django_db
class TestUnitAccess:
    def test_unit_inherits_course_level(self, django_user_model):
        user = django_user_model.objects.create_user(email="u@example.com")
        unit = paid_unit()

        assert can_access(user, unit) is False

    def test_unit_level_override_wins(self, django_user_model):
        user = django_user_model.objects.create_user(email="v@example.com")
        unit = paid_unit(required_level=0)

        assert can_access(user, unit) is True

    def test_purchase_hook_grants_unit_access(self, django_user_model, settings):
        settings.COMMUNITY_BASE = open_policy_settings("tests.curriculum.test_access.granted")
        user = django_user_model.objects.create_user(email="w@example.com")
        unit = paid_unit()

        assert can_access(user, unit) is True

    def test_registered_level_requires_authentication(self, django_user_model):
        course = make_course(slug="reg-course", title="Reg", default_unit_required_level=5)
        unit = make_unit(make_module(make_cohort(course)))

        assert can_access(None, unit) is False
        user = django_user_model.objects.create_user(email="x@example.com")
        assert can_access(user, unit) is True

    def test_is_preview_is_not_part_of_can_access(self):
        preview = paid_unit(slug="preview", is_preview=True)

        assert can_access(None, preview) is False
