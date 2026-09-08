"""Member API tests for the coursework learner flows.

The routes are registry routes mounted under ``/api/v1/`` by the testproject
urlconf, so these tests run against the default ``ROOT_URLCONF``.
"""

import json

import pytest
from django.contrib.auth import get_user_model

from community_base.coursework.leaderboard import LEADERBOARD_PAGE_SIZE
from community_base.curriculum.models import Enrollment
from tests.coursework.test_models import coursework_cohort

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_leaderboard_cache():
    """Cohort ids repeat across rolled-back tests; the cache outlives them."""

    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def preferences_url(cohort):
    return f"/api/v1/courses/{cohort.course.slug}/cohorts/{cohort.slug}/enrollment-preferences"


def leaderboard_url(cohort):
    return f"/api/v1/courses/{cohort.course.slug}/cohorts/{cohort.slug}/leaderboard"


def post_preference(client, cohort, field, value):
    return client.post(
        preferences_url(cohort),
        data=json.dumps({"field": field, "value": value}),
        content_type="application/json",
    )


def test_preference_toggle_requires_the_signed_in_member(client):
    cohort = coursework_cohort()

    response = post_preference(client, cohort, "display_on_leaderboard", "false")

    assert response.status_code == 401


def test_preference_toggle_updates_the_enrollment(client):
    cohort = coursework_cohort()
    member = get_user_model().objects.create_user(email="toggle@example.com")
    enrollment = Enrollment.objects.create(user=member, cohort=cohort)
    client.force_login(member)

    first = post_preference(client, cohort, "display_on_leaderboard", "false")
    second = post_preference(client, cohort, "display_on_leaderboard", "false")

    assert first.status_code == 200
    assert first.json() == {
        "enrollment": {"id": enrollment.id},
        "field": "display_on_leaderboard",
        "enabled": False,
        "changed": True,
    }
    enrollment.refresh_from_db()
    assert enrollment.display_on_leaderboard is False
    assert second.status_code == 200
    assert second.json()["changed"] is False


def test_preference_toggle_rejects_unknown_field_and_missing_enrollment(client):
    cohort = coursework_cohort()
    member = get_user_model().objects.create_user(email="outsider@example.com")
    client.force_login(member)

    unknown = post_preference(client, cohort, "display_name", "true")
    missing = post_preference(client, cohort, "display_on_leaderboard", "true")

    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "unknown_field"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_enrolled"


def test_leaderboard_api_requires_the_signed_in_member(client):
    cohort = coursework_cohort()

    response = client.get(leaderboard_url(cohort))

    assert response.status_code == 401


def test_leaderboard_api_returns_ranked_rows_for_a_member(client):
    cohort = coursework_cohort()
    Enrollment.objects.create(
        user=get_user_model().objects.create_user(email="first@example.com"),
        cohort=cohort,
        display_name="First Learner",
        total_score=9,
    )
    Enrollment.objects.create(
        user=get_user_model().objects.create_user(email="second@example.com"),
        cohort=cohort,
        display_name="Second Learner",
        total_score=4,
    )
    member = get_user_model().objects.create_user(email="reader@example.com")
    client.force_login(member)

    response = client.get(leaderboard_url(cohort))

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["page"] == 1
    assert payload["page_size"] == LEADERBOARD_PAGE_SIZE
    assert [row["display_name"] for row in payload["leaderboard"]] == [
        "First Learner",
        "Second Learner",
    ]
    assert [row["total_score"] for row in payload["leaderboard"]] == [9, 4]


def test_leaderboard_api_serves_the_requested_page(client):
    cohort = coursework_cohort()
    for index in range(LEADERBOARD_PAGE_SIZE + 1):
        Enrollment.objects.create(
            user=get_user_model().objects.create_user(email=f"paged{index}@example.com"),
            cohort=cohort,
            display_name=f"Learner {index:03d}",
            total_score=LEADERBOARD_PAGE_SIZE + 1 - index,
        )
    member = get_user_model().objects.create_user(email="pager@example.com")
    client.force_login(member)

    response = client.get(leaderboard_url(cohort), {"page": 2})

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 2
    assert payload["count"] == LEADERBOARD_PAGE_SIZE + 1
    assert len(payload["leaderboard"]) == 1
    assert payload["leaderboard"][0]["display_name"] == "Learner 100"
