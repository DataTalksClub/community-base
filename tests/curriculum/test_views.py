import datetime

import pytest
from django.utils import timezone

from community_base.curriculum.models import Cohort
from community_base.curriculum.services import ensure_enrollment
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


def paid_setup(required_level=10):
    course = make_course(slug="paid", title="Paid Course", required_level=required_level)
    cohort = make_cohort(course)
    module = make_module(cohort)
    unit = make_unit(module)
    return course, cohort, module, unit


def enroll(user, cohort):
    ensure_enrollment(user, cohort)


def test_catalog_lists_published_courses_only(client):
    make_course()
    make_course(slug="draft-course", title="Draft", status="draft")

    response = client.get("/courses/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Test Course" in body
    assert "Draft" not in body


def test_course_detail_shows_cohorts(client):
    course = make_course()
    cohort = make_cohort(course)

    response = client.get(f"/courses/{course.slug}/")

    assert response.status_code == 200
    assert cohort.title in response.content.decode()


def test_paid_course_detail_shows_gate_for_anonymous(client):
    course = paid_setup()[0]

    response = client.get(f"/courses/{course.slug}/")

    assert response.status_code == 200
    assert "Paid" in response.content.decode()


def test_unit_gated_for_paid_course(client):
    _course, _cohort, _module, unit = paid_setup()

    response = client.get(
        f"/courses/paid/{unit.module.cohort.slug}/{unit.module.slug}/{unit.slug}/"
    )

    assert response.status_code == 403
    assert "Sign in" in response.content.decode()


def test_unit_preview_open_to_everyone(client):
    _course, cohort, module, _unit = paid_setup()
    make_unit(module, slug="teaser", title="Teaser", is_preview=True)

    response = client.get(f"/courses/paid/{cohort.slug}/{module.slug}/teaser/")

    assert response.status_code == 200


def test_unit_open_for_enrolled_learner_on_open_course(client, django_user_model):
    user = django_user_model.objects.create_user(email="learner@example.com")
    course = make_course()
    cohort = make_cohort(course)
    module = make_module(cohort)
    unit = make_unit(module)
    ensure_enrollment(user, cohort)
    client.force_login(user)

    response = client.get(f"/courses/{course.slug}/{cohort.slug}/{module.slug}/{unit.slug}/")

    assert response.status_code == 200


def test_drip_locks_unit_for_cohort_started_today(client, django_user_model):
    user = django_user_model.objects.create_user(email="dripped@example.com")
    course = make_course(slug="drip-course", title="Drip Course")
    cohort = make_cohort(course)
    cohort.start_date = timezone.now().date()
    cohort.save()
    module = make_module(cohort)
    dripped = make_unit(module, slug="day-7", title="Day 7", available_after_days=7)
    open_unit = make_unit(module, slug="day-1", title="Day 1")
    ensure_enrollment(user, cohort)
    client.force_login(user)

    locked = client.get(f"/courses/{course.slug}/{cohort.slug}/{module.slug}/{dripped.slug}/")
    available = client.get(f"/courses/{course.slug}/{cohort.slug}/{module.slug}/{open_unit.slug}/")

    assert locked.status_code == 403
    assert "opens on" in locked.content.decode()
    assert available.status_code == 200


def test_drip_opens_after_available_date(client, django_user_model):
    user = django_user_model.objects.create_user(email="later@example.com")
    course = make_course(slug="drip2", title="Drip 2")
    cohort = make_cohort(course)
    cohort.start_date = datetime.date.today() - datetime.timedelta(days=8)
    cohort.save()
    module = make_module(cohort)
    unit = make_unit(module, slug="day-7", title="Day 7", available_after_days=7)
    ensure_enrollment(user, cohort)
    client.force_login(user)

    response = client.get(f"/courses/{course.slug}/{cohort.slug}/{module.slug}/{unit.slug}/")

    assert response.status_code == 200


def test_module_overview_lists_lessons(client):
    course = make_course()
    cohort = make_cohort(course)
    module = make_module(cohort)
    make_unit(module)

    response = client.get(f"/courses/{course.slug}/{cohort.slug}/{module.slug}/")

    assert response.status_code == 200
    assert "Welcome" in response.content.decode()


def test_course_enroll_redirects_and_creates_self_paced_enrollment(client, django_user_model):
    user = django_user_model.objects.create_user(email="enroll@example.com")
    course = make_course()
    client.force_login(user)

    response = client.post(f"/courses/{course.slug}/enroll/")

    assert response.status_code == 302
    cohort = Cohort.objects.get(course=course, mode="self_paced")
    assert cohort.enrollments.filter(user=user, unenrolled_at__isnull=True).exists()


def test_course_enroll_denied_without_access(client, django_user_model):
    user = django_user_model.objects.create_user(email="paywalled@example.com")
    course, _cohort, _module, _unit = paid_setup()
    client.force_login(user)

    client.post(f"/courses/{course.slug}/enroll/")

    assert not Cohort.objects.filter(course=course, enrollments__user=user).exists()


def test_course_unenroll(client, django_user_model):
    user = django_user_model.objects.create_user(email="bye@example.com")
    course = make_course()
    client.force_login(user)
    client.post(f"/courses/{course.slug}/enroll/")

    response = client.post(f"/courses/{course.slug}/unenroll/")

    assert response.status_code == 302
    cohort = Cohort.objects.get(course=course, mode="self_paced")
    assert not cohort.enrollments.filter(user=user, unenrolled_at__isnull=True).exists()


def test_cohort_enroll_api_flow(client, django_user_model):
    user = django_user_model.objects.create_user(email="cohort@example.com")
    course = make_course()
    cohort = make_cohort(course)
    client.force_login(user)
    url = f"/courses/{course.slug}/cohorts/{cohort.slug}/enroll/"

    enrolled = client.post(url)
    again = client.post(url)

    assert enrolled.status_code == 200
    assert enrolled.json()["enrolled"] is True
    assert again.status_code == 409


def test_cohort_enroll_requires_authentication(client):
    course = make_course()
    cohort = make_cohort(course)

    response = client.post(f"/courses/{course.slug}/cohorts/{cohort.slug}/enroll/")

    assert response.status_code == 401


def test_cohort_enroll_full(client, django_user_model):
    course = make_course()
    cohort = make_cohort(course, max_participants=1)
    other = django_user_model.objects.create_user(email="full1@example.com")
    ensure_enrollment(other, cohort)
    user = django_user_model.objects.create_user(email="full2@example.com")
    client.force_login(user)

    response = client.post(f"/courses/{course.slug}/cohorts/{cohort.slug}/enroll/")

    assert response.status_code == 409
    assert response.json()["error"] == "Cohort is full"


def test_cohort_unenroll_api(client, django_user_model):
    user = django_user_model.objects.create_user(email="leave@example.com")
    course = make_course()
    cohort = make_cohort(course)
    ensure_enrollment(user, cohort)
    client.force_login(user)
    url = f"/courses/{course.slug}/cohorts/{cohort.slug}/unenroll/"

    response = client.post(url)
    repeat = client.post(url)

    assert response.status_code == 200
    assert repeat.status_code == 404


def test_api_courses_lists_with_lock_flags(client, django_user_model):
    make_course()
    paid_setup()

    response = client.get("/courses/api/courses/")

    data = response.json()
    by_slug = {item["slug"]: item for item in data["courses"]}
    assert by_slug["test-course"]["is_locked"] is False
    assert by_slug["paid"]["is_locked"] is True


def test_api_course_detail_with_progress(client, django_user_model):
    user = django_user_model.objects.create_user(email="api@example.com")
    course = make_course()
    cohort = make_cohort(course)
    module = make_module(cohort)
    unit = make_unit(module)
    client.force_login(user)

    response = client.get(f"/courses/api/courses/{course.slug}/")

    data = response.json()
    assert data["progress"] == {"completed": 0, "total": 1}
    assert data["syllabus"][0]["modules"][0]["units"][0]["slug"] == unit.slug


def test_api_unit_detail_gates_paid_content(client):
    _course, _cohort, _module, unit = paid_setup()

    response = client.get(f"/courses/paid/units/{unit.pk}/")

    assert response.status_code == 401


def test_api_unit_detail_and_complete_toggle(client, django_user_model):
    user = django_user_model.objects.create_user(email="toggle@example.com")
    course = make_course()
    cohort = make_cohort(course)
    module = make_module(cohort)
    unit = make_unit(module)
    ensure_enrollment(user, cohort)
    client.force_login(user)
    detail_url = f"/courses/{course.slug}/units/{unit.pk}/"
    complete_url = f"/courses/{course.slug}/units/{unit.pk}/complete/"

    detail = client.get(detail_url)
    marked = client.post(complete_url)
    unmarked = client.post(complete_url)

    assert detail.status_code == 200
    assert marked.json() == {"completed": True}
    assert unmarked.json() == {"completed": False}
    assert client.get(detail_url).json()["is_completed"] is False


def test_api_unit_complete_requires_access(client, django_user_model):
    user = django_user_model.objects.create_user(email="nope@example.com")
    _course, _cohort, _module, unit = paid_setup()
    client.force_login(user)

    response = client.post(f"/courses/paid/units/{unit.pk}/complete/")

    assert response.status_code == 403


def test_mark_completed_creates_self_paced_enrollment_via_api(client, django_user_model):
    user = django_user_model.objects.create_user(email="autoenroll@example.com")
    course = make_course()
    cohort = make_cohort(course)
    module = make_module(cohort)
    unit = make_unit(module)
    client.force_login(user)

    client.post(f"/courses/{course.slug}/units/{unit.pk}/complete/")

    assert cohort.enrollments.filter(user=user, unenrolled_at__isnull=True).exists()
