import pytest
from django.core.cache import cache

from community_base.accounts.models import User
from community_base.api.models import APIKey
from community_base.coursework import leaderboard
from tests.coursework.test_models import coursework_cohort, coursework_course, enrollment_for

pytestmark = pytest.mark.django_db


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def reader_key(db):
    user = User.objects.create_user(email="coursework-api@example.com", is_staff=True)
    _, key = APIKey.create_for_user(
        user=user,
        name="Coursework reader",
        scopes=["coursework.read"],
        kind=APIKey.Kind.STAFF,
    )
    return key


@pytest.fixture
def foreign_key(db):
    user = User.objects.create_user(email="coursework-other@example.com", is_staff=True)
    _, key = APIKey.create_for_user(
        user=user,
        name="Unrelated reader",
        scopes=["curriculum.read"],
        kind=APIKey.Kind.STAFF,
    )
    return key


def test_leaderboard_api_requires_coursework_read_scope(client, foreign_key, reader_key):
    course = coursework_course()
    cohort = coursework_cohort()

    denied = client.get(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/leaderboard",
        headers=bearer(foreign_key),
    )
    allowed = client.get(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/leaderboard",
        headers=bearer(reader_key),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {
        "leaderboard": [],
        "page": 1,
        "page_size": leaderboard.LEADERBOARD_PAGE_SIZE,
        "count": 0,
    }


def test_leaderboard_api_returns_visible_rows_in_position_order(client, reader_key):
    course = coursework_course()
    cohort = coursework_cohort(slug="lb-api")
    _user, hidden = enrollment_for(cohort, email="hidden@example.com")
    hidden.display_on_leaderboard = False
    hidden.save()
    _user, shown = enrollment_for(cohort, email="shown@example.com")
    shown.display_name = "Shown Learner"
    shown.save()
    leaderboard.update_leaderboard(cohort)

    response = client.get(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/leaderboard",
        headers=bearer(reader_key),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert [row["display_name"] for row in payload["leaderboard"]] == ["Shown Learner"]
    # Donor parity: hidden learners still occupy positions; only display is filtered.
    assert payload["leaderboard"][0]["position_on_leaderboard"] == 2


def test_leaderboard_api_pages_rows(client, reader_key):
    course = coursework_course()
    cohort = coursework_cohort(slug="lb-pages")
    for number in range(3):
        enrollment_for(cohort, email=f"paged-{number}@example.com")
    leaderboard.update_leaderboard(cohort)

    url = f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/leaderboard"
    original_page_size = leaderboard.LEADERBOARD_PAGE_SIZE
    leaderboard.LEADERBOARD_PAGE_SIZE = 2
    try:
        first = client.get(url, headers=bearer(reader_key))
        second = client.get(f"{url}?page=2", headers=bearer(reader_key))
    finally:
        leaderboard.LEADERBOARD_PAGE_SIZE = original_page_size

    assert first.json()["page_size"] == 2
    assert len(first.json()["leaderboard"]) == 2
    assert second.json()["page"] == 2
    assert len(second.json()["leaderboard"]) == 1
    assert second.json()["count"] == 3


def test_leaderboard_api_unknown_cohort(client, reader_key):
    course = coursework_course()

    response = client.get(
        f"/api/v1/courses/{course.slug}/cohorts/missing/leaderboard",
        headers=bearer(reader_key),
    )

    assert response.status_code == 404


def test_preference_toggle_via_api_updates_and_invalidates_cache(client):
    course = coursework_course()
    cohort = coursework_cohort(slug="pref-api")
    _user, enrollment = enrollment_for(cohort)
    leaderboard.update_leaderboard(cohort)
    nobody = leaderboard.CurrentLeaderboardStudent(enrollment=None, enrollment_id=None)
    leaderboard.get_leaderboard_data(cohort, nobody)
    assert cache.get(f"leaderboard:{cohort.id}") is not None
    client.force_login(enrollment.user)

    response = client.post(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/enrollment-preferences",
        data='{"field": "display_on_leaderboard", "value": "false"}',
        content_type="application/json",
    )
    repeat = client.post(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/enrollment-preferences",
        data='{"field": "display_on_leaderboard", "value": "false"}',
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["changed"] is True
    assert payload["enabled"] is False
    assert payload["enrollment"]["display_on_leaderboard"] is False
    assert cache.get(f"leaderboard:{cohort.id}") is None
    assert repeat.json()["changed"] is False


def test_preference_api_rejects_unknown_field(client):
    course = coursework_course()
    cohort = coursework_cohort(slug="pref-bad")
    _user, enrollment = enrollment_for(cohort)
    client.force_login(enrollment.user)

    response = client.post(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/enrollment-preferences",
        data='{"field": "display_name", "value": "Spoofed"}',
        content_type="application/json",
    )

    assert response.status_code == 422
    enrollment.refresh_from_db()
    assert enrollment.display_name != "Spoofed"


def test_preference_api_requires_enrollment(client):
    course = coursework_course()
    cohort = coursework_cohort(slug="pref-none")
    user = User.objects.create_user(email="unenrolled@example.com")
    client.force_login(user)

    response = client.post(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/enrollment-preferences",
        data='{"field": "display_on_leaderboard", "value": "true"}',
        content_type="application/json",
    )

    assert response.status_code == 404


def test_preference_api_requires_login(client):
    course = coursework_course()
    cohort = coursework_cohort(slug="pref-anon")

    response = client.post(
        f"/api/v1/courses/{course.slug}/cohorts/{cohort.slug}/enrollment-preferences",
        data='{"field": "display_on_leaderboard", "value": "true"}',
        content_type="application/json",
    )

    assert response.status_code == 401
