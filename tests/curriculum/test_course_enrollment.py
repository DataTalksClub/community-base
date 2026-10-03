import pytest
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from community_base.coursework import models as coursework_models
from community_base.curriculum import models as curriculum_models
from community_base.curriculum import services as curriculum_services

pytestmark = pytest.mark.django_db


def test_ensure_course_enrollment_is_idempotent_and_creates_no_cohort(django_user_model):
    assert hasattr(curriculum_models, "CourseEnrollment"), "CourseEnrollment capability is missing"
    assert hasattr(curriculum_services, "ensure_course_enrollment"), (
        "ensure_course_enrollment capability is missing"
    )
    course_enrollment_model = curriculum_models.CourseEnrollment
    ensure_course_enrollment = curriculum_services.ensure_course_enrollment
    user = django_user_model.objects.create_user(email="learner@example.com")
    course = curriculum_models.Course.objects.create(slug="course", title="Course")

    enrollment, created = ensure_course_enrollment(user, course)
    first_enrolled_at = enrollment.enrolled_at
    again, created_again = ensure_course_enrollment(user, course, source="admin")

    assert created is True
    assert created_again is False
    assert again.pk == enrollment.pk
    assert again.source == "manual"
    assert again.enrolled_at == first_enrolled_at
    assert enrollment.is_active is True
    assert list(curriculum_services.course_enrollment_history(user, course=course)) == [enrollment]
    assert course_enrollment_model.objects.filter(user=user, course=course).count() == 1
    assert curriculum_models.Cohort.objects.filter(course=course).count() == 0


def test_course_enrollment_value_field_contract():
    model = curriculum_models.CourseEnrollment
    enrolled_field = model._meta.get_field("enrolled_at")
    unenrolled_field = model._meta.get_field("unenrolled_at")
    source_field = model._meta.get_field("source")

    assert model._meta.pk.get_internal_type() == "BigAutoField"
    assert enrolled_field.auto_now_add is True
    assert enrolled_field.null is False
    assert enrolled_field.default is models.NOT_PROVIDED
    assert enrolled_field.db_index is False
    assert unenrolled_field.null is True
    assert unenrolled_field.blank is True
    assert unenrolled_field.default is models.NOT_PROVIDED
    assert unenrolled_field.db_index is False
    assert source_field.max_length == 20
    assert source_field.null is False
    assert source_field.blank is False
    assert source_field.default == curriculum_models.SOURCE_MANUAL == "manual"
    assert tuple(source_field.choices) == (
        ("manual", "Manual"),
        ("auto_progress", "Auto (first lesson complete)"),
        ("admin", "Admin (Studio)"),
    )


def test_course_enrollment_relation_and_constraint_contract():
    model = curriculum_models.CourseEnrollment
    user_field = model._meta.get_field("user")
    course_field = model._meta.get_field("course")
    constraint = model._meta.constraints[0]

    assert user_field.null is False
    assert user_field.remote_field.on_delete is models.CASCADE
    assert user_field.remote_field.related_name == "curriculum_course_enrollments"
    assert course_field.null is False
    assert course_field.remote_field.model is curriculum_models.Course
    assert course_field.remote_field.on_delete is models.CASCADE
    assert course_field.remote_field.related_name == "course_enrollments"
    assert constraint.name == "cb_course_enroll_active_uq"
    assert constraint.fields == ("user", "course")
    assert constraint.condition == models.Q(unenrolled_at__isnull=True)


def test_course_enrollment_display_and_ordering(django_user_model):
    model = curriculum_models.CourseEnrollment
    assert model._meta.ordering == ("-enrolled_at",)

    user = django_user_model.objects.create_user(email="contract@example.com")
    course = curriculum_models.Course.objects.create(slug="contract", title="Contract")
    enrollment = model.objects.create(user=user, course=course)

    assert str(enrollment) == f"{user} -> Contract (active)"
    enrollment.unenrolled_at = timezone.now()
    assert enrollment.is_active is False
    assert str(enrollment) == f"{user} -> Contract (unenrolled)"


def test_existing_cohort_source_contract_is_unchanged():
    source_field = curriculum_models.Enrollment._meta.get_field("source")

    assert source_field.max_length == 20
    assert source_field.default == "manual"
    assert tuple(source_field.choices) == curriculum_models.ENROLLMENT_SOURCES
    assert curriculum_models.ENROLLMENT_SOURCES == (
        ("manual", "Manual"),
        ("auto_progress", "Auto (first lesson complete)"),
        ("admin", "Admin (Studio)"),
    )


def test_active_uniqueness_soft_close_and_reenrollment(django_user_model):
    model = curriculum_models.CourseEnrollment
    user = django_user_model.objects.create_user(email="history@example.com")
    course = curriculum_models.Course.objects.create(slug="history", title="History")
    original = model.objects.create(user=user, course=course, source="admin")
    original_enrolled_at = original.enrolled_at

    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(user=user, course=course, source="manual")

    existing, created = curriculum_services.ensure_course_enrollment(
        user, course, source="auto_progress"
    )
    assert (existing.pk, created) == (original.pk, False)
    assert existing.source == "admin"
    assert existing.enrolled_at == original_enrolled_at
    assert curriculum_services.unenroll_from_course(user, course) is True
    assert curriculum_services.unenroll_from_course(user, course) is False

    replacement, created = curriculum_services.ensure_course_enrollment(
        user, course, source="auto_progress"
    )
    original.refresh_from_db()
    assert created is True
    assert replacement.pk != original.pk
    assert replacement.source == "auto_progress"
    assert original.unenrolled_at is not None
    assert original.enrolled_at == original_enrolled_at


def test_history_scope_order_and_active_count(django_user_model):
    model = curriculum_models.CourseEnrollment
    user = django_user_model.objects.create_user(email="scope@example.com")
    other_user = django_user_model.objects.create_user(email="other@example.com")
    course = curriculum_models.Course.objects.create(slug="scope", title="Scope")
    other_course = curriculum_models.Course.objects.create(slug="other", title="Other")
    old = model.objects.create(user=user, course=course, source="manual")
    curriculum_services.unenroll_from_course(user, course)
    active = model.objects.create(user=user, course=course, source="admin")
    other_course_row = model.objects.create(user=user, course=other_course)
    model.objects.create(user=other_user, course=course)

    earlier = timezone.now() - timezone.timedelta(days=1)
    model.objects.filter(pk=old.pk).update(enrolled_at=earlier)

    assert list(
        curriculum_services.course_enrollment_history(user, course=course).values_list(
            "pk", flat=True
        )
    ) == [active.pk, old.pk]
    assert set(
        curriculum_services.course_enrollment_history(user).values_list("pk", flat=True)
    ) == {old.pk, active.pk, other_course_row.pk}
    assert curriculum_services.active_course_enrollment_count(course) == 2


def test_unauthenticated_course_enrollment_results():
    course = curriculum_models.Course(slug="unsaved", title="Unsaved")

    assert curriculum_services.get_active_course_enrollment(None, course) is None
    assert curriculum_services.is_course_enrolled(None, course) is False
    assert curriculum_services.ensure_course_enrollment(None, course) == (None, False)
    assert curriculum_services.unenroll_from_course(None, course) is False
    history = curriculum_services.course_enrollment_history(None, course=course)
    assert history.model is curriculum_models.CourseEnrollment
    assert list(history) == []


def test_course_mutations_do_not_call_cohort_helpers(monkeypatch, django_user_model):
    def fail(*args, **kwargs):
        pytest.fail("course enrollment called a cohort mutation helper")

    monkeypatch.setattr(curriculum_services, "ensure_enrollment", fail)
    monkeypatch.setattr(curriculum_services, "unenroll", fail)
    monkeypatch.setattr(curriculum_services, "get_or_create_self_paced_cohort", fail)
    user = django_user_model.objects.create_user(email="isolated@example.com")
    course = curriculum_models.Course.objects.create(slug="isolated", title="Isolated")

    enrollment, created = curriculum_services.ensure_course_enrollment(user, course)
    assert created is True
    assert curriculum_services.unenroll_from_course(user, course) is True
    assert enrollment.course_id == course.pk
    assert course.cohorts.count() == 0


def test_course_mutations_preserve_same_course_cohort_row(django_user_model):
    user = django_user_model.objects.create_user(email="cohort@example.com")
    course = curriculum_models.Course.objects.create(slug="cohort", title="Cohort")
    cohort = curriculum_models.Cohort.objects.create(
        course=course,
        slug="2026",
        title="2026",
    )
    cohort_enrollment = curriculum_models.Enrollment.objects.create(
        user=user,
        cohort=cohort,
        source="admin",
        display_name="Learner",
        total_score=42,
    )
    before = curriculum_models.Enrollment.objects.values().get(pk=cohort_enrollment.pk)

    curriculum_services.ensure_course_enrollment(user, course)
    curriculum_services.unenroll_from_course(user, course)
    curriculum_services.ensure_course_enrollment(user, course, source="auto_progress")

    after = curriculum_models.Enrollment.objects.values().get(pk=cohort_enrollment.pk)
    assert after == before


def test_course_and_cohort_enrollments_have_separate_pk_namespaces(django_user_model):
    user = django_user_model.objects.create_user(email="namespace@example.com")
    course = curriculum_models.Course.objects.create(slug="namespace", title="Namespace")
    cohort = curriculum_models.Cohort.objects.create(course=course, slug="one", title="One")

    cohort_row = curriculum_models.Enrollment.objects.create(pk=777, user=user, cohort=cohort)
    course_row = curriculum_models.CourseEnrollment.objects.create(
        pk=777,
        user=user,
        course=course,
    )

    assert cohort_row.pk == course_row.pk == 777
    assert type(cohort_row) is curriculum_models.Enrollment
    assert type(course_row) is curriculum_models.CourseEnrollment


def test_coursework_and_certificate_relations_remain_cohort_typed(django_user_model):
    relation_owners = (
        coursework_models.Submission,
        coursework_models.ProjectSubmission,
        coursework_models.LeaderboardComplaint,
        curriculum_models.Certificate,
    )
    for owner in relation_owners:
        assert (
            owner._meta.get_field("enrollment").remote_field.model is curriculum_models.Enrollment
        )

    user = django_user_model.objects.create_user(email="relations@example.com")
    course = curriculum_models.Course.objects.create(slug="relations", title="Relations")
    course_enrollment = curriculum_models.CourseEnrollment.objects.create(
        user=user,
        course=course,
    )
    for owner in relation_owners:
        with pytest.raises(ValueError):
            owner(enrollment=course_enrollment)


def test_authentication_predicate_is_reexported_without_wrapping():
    from community_base.curriculum import enrollment_services

    assert curriculum_services._is_authenticated is enrollment_services._is_authenticated
