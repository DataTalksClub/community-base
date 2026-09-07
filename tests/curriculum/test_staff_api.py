import pytest

from community_base.accounts.models import User
from community_base.api.models import APIKey
from community_base.curriculum.models import (
    Certificate,
    Enrollment,
)
from community_base.events.models import Host
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture
def staff_keys(db):
    user = User.objects.create_user(email="curriculum-api@example.com", is_staff=True)
    _, read_key = APIKey.create_for_user(
        user=user,
        name="Curriculum reader",
        scopes=["curriculum.read"],
        kind=APIKey.Kind.STAFF,
    )
    _, write_key = APIKey.create_for_user(
        user=user,
        name="Curriculum writer",
        scopes=["curriculum.write"],
        kind=APIKey.Kind.STAFF,
    )
    return read_key, write_key


@pytest.fixture
def course_setup():
    course = make_course(slug="api-course", title="API Course")
    cohort = make_cohort(course, mode="self_paced", title="Self-paced")
    module = make_module(cohort)
    unit = make_unit(module)
    return course, cohort, module, unit


def test_enrollments_api_requires_read_scope(client, course_setup, staff_keys):
    read_key, write_key = staff_keys

    denied = client.get("/api/v1/courses/api-course/enrollments", headers=bearer(write_key))
    allowed = client.get("/api/v1/courses/api-course/enrollments", headers=bearer(read_key))

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {"enrollments": []}


def test_bulk_enroll_reports_four_buckets(client, django_user_model, staff_keys, course_setup):
    _read_key, write_key = staff_keys
    course = course_setup[0]
    known = django_user_model.objects.create_user(email="bulk@example.com")
    existing = django_user_model.objects.create_user(email="already@example.com")
    Enrollment.objects.create(user=existing, cohort=course.cohorts.first())

    response = client.post(
        "/api/v1/courses/api-course/enrollments",
        {"user_emails": ["bulk@example.com", "already@example.com", "ghost@example.com"]},
        content_type="application/json",
        headers=bearer(write_key),
    )

    data = response.json()
    assert response.status_code == 200
    assert data["enrolled"] == 1
    assert data["already_enrolled"] == 1
    assert data["unknown_emails"] == ["ghost@example.com"]
    assert known.email in [known.email]
    assert Enrollment.objects.filter(user=known, cohort__course=course).exists()


def test_bulk_enroll_flags_learners_without_access(client, django_user_model, staff_keys):
    _read_key, write_key = staff_keys
    make_course(slug="paid-api", title="Paid API", required_level=10)
    locked = django_user_model.objects.create_user(email="locked@example.com")

    response = client.post(
        "/api/v1/courses/paid-api/enrollments",
        {"user_email": "Locked@example.com"},
        content_type="application/json",
        headers=bearer(write_key),
    )

    data = response.json()
    assert data["without_access"] == [locked.email]
    assert data["enrolled"] == 1


def test_delete_enrollment_is_idempotent(client, django_user_model, staff_keys, course_setup):
    _read_key, write_key = staff_keys
    course, cohort, _module, _unit = course_setup
    learner = django_user_model.objects.create_user(email="remove@example.com")
    Enrollment.objects.create(user=learner, cohort=cohort)

    first = client.delete(
        "/api/v1/courses/api-course/enrollments/remove@example.com",
        headers=bearer(write_key),
    )
    second = client.delete(
        "/api/v1/courses/api-course/enrollments/ghost@example.com",
        headers=bearer(write_key),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert not Enrollment.objects.filter(user=learner, unenrolled_at__isnull=True).exists()


def test_certificate_issue_list_and_delete_guard(
    client, django_user_model, staff_keys, course_setup
):
    read_key, write_key = staff_keys
    course, cohort, _module, _unit = course_setup
    learner = django_user_model.objects.create_user(email="cert@example.com")
    Enrollment.objects.create(user=learner, cohort=cohort)

    issued = client.post(
        "/api/v1/courses/api-course/certificates",
        {"user_email": "cert@example.com", "url": "https://certs.example.com/x.pdf"},
        content_type="application/json",
        headers=bearer(write_key),
    )
    listed = client.get("/api/v1/courses/api-course/certificates", headers=bearer(read_key))
    guarded = client.delete(
        "/api/v1/courses/api-course/certificates/cert@example.com",
        headers=bearer(write_key),
    )

    assert issued.status_code == 200
    assert issued.json()["url"].endswith(".pdf")
    assert listed.json()["certificates"][0]["user_email"] == "cert@example.com"
    assert guarded.status_code == 405
    assert "Studio" in guarded.json()["error"]["message"]
    assert Certificate.objects.filter(enrollment__user=learner).exists()


def test_certificate_rejects_invalid_url(client, django_user_model, staff_keys, course_setup):
    _read_key, write_key = staff_keys
    course, cohort, _module, _unit = course_setup
    learner = django_user_model.objects.create_user(email="badcert@example.com")
    Enrollment.objects.create(user=learner, cohort=cohort)

    response = client.post(
        "/api/v1/courses/api-course/certificates",
        {"user_email": "badcert@example.com", "url": "javascript:alert(1)"},
        content_type="application/json",
        headers=bearer(write_key),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_url"


def test_instructors_get_and_replace(client, staff_keys, course_setup):
    read_key, write_key = staff_keys
    course = course_setup[0]
    Host.objects.create(name="Ada", slug="ada", kind="instructor")
    Host.objects.create(name="Grace", slug="grace", kind="instructor")

    replaced = client.put(
        "/api/v1/courses/api-course/instructors",
        {"instructor_ids": ["ada", "grace"]},
        content_type="application/json",
        headers=bearer(write_key),
    )
    listed = client.get("/api/v1/courses/api-course/instructors", headers=bearer(read_key))

    assert replaced.status_code == 200
    assert [item["slug"] for item in replaced.json()["instructors"]] == ["ada", "grace"]
    assert listed.json() == replaced.json()
    assert [host.position for host in course.courseinstructor_set.all()] == [0, 1]


def test_instructors_replace_rejects_unknown_and_source_owned(client, staff_keys, course_setup):
    _read_key, write_key = staff_keys
    course = course_setup[0]

    unknown = client.put(
        "/api/v1/courses/api-course/instructors",
        {"instructor_ids": ["nobody"]},
        content_type="application/json",
        headers=bearer(write_key),
    )
    assert unknown.status_code == 422

    course.source_content_id = "3f2b4a1e-0000-4000-8000-000000000010"
    course.source_path = "courses/api-course/course.yaml"
    course.source_commit_sha = "a" * 40
    course.source_checksum = "b" * 64
    course.save()
    source_owned = client.put(
        "/api/v1/courses/api-course/instructors",
        {"instructor_ids": []},
        content_type="application/json",
        headers=bearer(write_key),
    )
    assert source_owned.status_code == 409
    assert source_owned.json()["error"]["code"] == "source_owned"


def test_unknown_course_returns_404(client, staff_keys):
    read_key, _ = staff_keys

    response = client.get("/api/v1/courses/nope/enrollments", headers=bearer(read_key))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_course"


def test_staff_routes_are_published_in_openapi(client):
    from community_base.api.openapi import build_document

    document = build_document()
    paths = document["paths"]
    assert any("enrollments" in path for path in paths)
    assert any("certificates" in path for path in paths)
    assert any("instructors" in path for path in paths)
