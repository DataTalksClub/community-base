import pytest
from django.urls import reverse

from community_base.accounts.models import User
from community_base.curriculum.models import (
    Certificate,
    Cohort,
    Course,
    Enrollment,
)
from community_base.events.models import Host
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user(email="staff@example.com", is_staff=True)
    client.force_login(user)
    return user


def course_with_content(source_content_id=None):
    course = make_course()
    if source_content_id:
        course.source_content_id = source_content_id
        course.source_path = "courses/test-course/course.yaml"
        course.source_commit_sha = "a" * 40
        course.source_checksum = "b" * 64
        course.save()
    cohort = make_cohort(course)
    module = make_module(cohort)
    unit = make_unit(module)
    return course, cohort, module, unit


def test_course_list_and_create(client, staff):
    course = make_course()

    listed = client.get(reverse("curriculum_studio_course_list"))
    created = client.post(
        reverse("curriculum_studio_course_create"),
        {
            "title": "New Course",
            "slug": "new-course",
            "status": "published",
            "required_level": "0",
            "visible": "on",
        },
    )

    assert listed.status_code == 200
    assert course.title in listed.content.decode()
    assert created.status_code == 302
    assert not Cohort.objects.filter(course__slug="new-course").exists()
    assert Course.objects.filter(slug="new-course").exists()


def test_course_detail_lists_cohorts(client, staff):
    course = make_course()
    cohort = make_cohort(course)

    response = client.get(reverse("curriculum_studio_course_detail", args=[course.pk]))

    assert response.status_code == 200
    assert cohort.title in response.content.decode()


def test_course_edit_and_delete(client, staff):
    course = make_course()

    updated = client.post(
        reverse("curriculum_studio_course_edit", args=[course.pk]),
        {
            "title": "Renamed",
            "slug": course.slug,
            "status": "published",
            "required_level": "0",
            "visible": "on",
        },
    )
    assert updated.status_code == 302
    course.refresh_from_db()
    assert course.title == "Renamed"

    deleted = client.post(reverse("curriculum_studio_course_delete", args=[course.pk]))
    assert deleted.status_code == 302
    assert not Course.objects.filter(pk=course.pk).exists()


def test_source_managed_course_rejects_edit(client, staff):
    course, _cohort, _module, _unit = course_with_content(
        source_content_id="3f2b4a1e-0000-4000-8000-000000000009"
    )

    response = client.post(
        reverse("curriculum_studio_course_edit", args=[course.pk]),
        {
            "title": "Should not apply",
            "slug": course.slug,
            "status": "published",
            "required_level": "0",
            "visible": "on",
        },
        follow=True,
    )

    course.refresh_from_db()
    assert course.title != "Should not apply"
    assert "source-managed" in response.content.decode().lower()


def test_cohort_crud_and_pages(client, staff):
    course = make_course()

    created = client.post(
        reverse("curriculum_studio_cohort_create", args=[course.pk]),
        {
            "title": "2026 cohort",
            "slug": "2026",
            "mode": "cohort",
            "curriculum_format": "legacy",
            "finished": "",
            "visible": "on",
        },
    )
    assert created.status_code == 302
    cohort = Cohort.objects.get(course=course, slug="2026")

    detail = client.get(reverse("curriculum_studio_cohort_detail", args=[cohort.pk]))
    assert detail.status_code == 200
    assert "2026 cohort" in detail.content.decode()

    edited = client.post(
        reverse("curriculum_studio_cohort_edit", args=[cohort.pk]),
        {
            "title": "2026 spring",
            "slug": "2026",
            "mode": "cohort",
            "curriculum_format": "legacy",
            "finished": "",
            "visible": "on",
        },
    )
    assert edited.status_code == 302
    cohort.refresh_from_db()
    assert cohort.title == "2026 spring"

    deleted = client.post(reverse("curriculum_studio_cohort_delete", args=[cohort.pk]))
    assert deleted.status_code == 302
    assert Cohort.objects.filter(course=course).count() == 0


def test_module_and_unit_management(client, staff):
    course = make_course()
    cohort = make_cohort(course)

    module_created = client.post(
        reverse("curriculum_studio_module_create", args=[cohort.pk]),
        {"title": "Module 1", "slug": "module-1", "sort_order": "1"},
    )
    assert module_created.status_code == 302
    module = cohort.modules.get(slug="module-1")

    unit_created = client.post(
        reverse("curriculum_studio_unit_create", args=[module.pk]),
        {"title": "Lesson 1", "slug": "lesson-1", "sort_order": "1"},
    )
    assert unit_created.status_code == 302
    unit = module.units.get(slug="lesson-1")

    unit_edited = client.post(
        reverse("curriculum_studio_unit_edit", args=[unit.pk]),
        {"title": "Lesson 1 renamed", "slug": unit.slug, "sort_order": "1"},
    )
    assert unit_edited.status_code == 302
    unit.refresh_from_db()
    assert unit.title == "Lesson 1 renamed"

    unit_deleted = client.post(reverse("curriculum_studio_unit_delete", args=[unit.pk]))
    module_deleted = client.post(reverse("curriculum_studio_module_delete", args=[module.pk]))

    assert unit_deleted.status_code == 302
    assert module_deleted.status_code == 302
    assert cohort.modules.count() == 0


def test_instructor_management(client, staff):
    course = make_course()
    Host.objects.create(name="Ada Lovelace", slug="ada", kind="instructor")

    added = client.post(
        reverse("curriculum_studio_instructor_add", args=[course.pk]), {"host": "ada"}
    )
    assert added.status_code == 302
    assert course.ordered_instructors == [Host.objects.get(slug="ada")]

    link = course.courseinstructor_set.first()
    removed = client.post(reverse("curriculum_studio_instructor_remove", args=[course.pk, link.pk]))
    assert removed.status_code == 302
    assert course.ordered_instructors == []


def test_enrollment_and_certificate_management(client, staff):
    course = make_course()
    cohort = make_cohort(course)
    learner = User.objects.create_user(email="learner@example.com")

    enrolled = client.post(
        reverse("curriculum_studio_enrollment_create", args=[cohort.pk]),
        {"email": "LEARNER@example.com"},
    )
    assert enrolled.status_code == 302
    enrollment = Enrollment.objects.get(cohort=cohort, user=learner)

    issued = client.post(
        reverse("curriculum_studio_certificate_issue", args=[enrollment.pk]),
        {"url": "https://certs.example.com/learner.pdf"},
    )
    assert issued.status_code == 302
    assert Certificate.objects.get(enrollment=enrollment).url.endswith(".pdf")

    removed = client.post(reverse("curriculum_studio_enrollment_delete", args=[enrollment.pk]))
    assert removed.status_code == 302
    assert not Enrollment.objects.filter(pk=enrollment.pk).exists()


def test_studio_requires_staff(client, django_user_model):
    django_user_model.objects.create_user(email="member@example.com")
    client.force_login(User.objects.get(email="member@example.com"))

    response = client.get(reverse("curriculum_studio_course_list"))

    assert response.status_code == 403


def test_studio_section_registered():
    from community_base.studio.registry import sections

    slugs = [section.slug for section in sections()]
    assert "courses" in slugs
