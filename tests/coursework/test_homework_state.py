"""Homework state change: service, staff bearer API and Studio action.

CMP parity: any of ``CL``/``OP``/``SC`` is accepted as is, with no transition
table, and an unknown value is refused with ``invalid_homework_state``.
"""

import json

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from community_base.accounts.models import User
from community_base.api.models import APIKey
from community_base.coursework.homework_state import (
    VALID_HOMEWORK_STATES,
    InvalidHomeworkState,
    close_homework,
    parse_homework_state,
    set_homework_state,
)
from community_base.coursework.models import HomeworkState
from community_base.coursework.scoring import score_homework_submissions
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_models import homework as make_homework

pytestmark = pytest.mark.django_db


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


def state_url(hw, action="state"):
    cohort = hw.cohort
    return (
        f"/api/v1/courses/{cohort.course.slug}/cohorts/{cohort.slug}/homeworks/{hw.slug}/{action}"
    )


@pytest.fixture
def keys(db):
    user = User.objects.create_user(email="coursework-api@example.com", is_staff=True)
    _, read_key = APIKey.create_for_user(
        user=user, name="Coursework reader", scopes=["coursework.read"], kind=APIKey.Kind.STAFF
    )
    _, write_key = APIKey.create_for_user(
        user=user, name="Coursework writer", scopes=["coursework.write"], kind=APIKey.Kind.STAFF
    )
    return read_key, write_key


# --- service ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (HomeworkState.CLOSED, HomeworkState.CLOSED),
        ("CL", HomeworkState.CLOSED),
        ("op", HomeworkState.OPEN),
        ("scored", HomeworkState.SCORED),
        (" Closed ", HomeworkState.CLOSED),
        ("OPEN", HomeworkState.OPEN),
    ],
)
def test_parse_homework_state_accepts_codes_and_names(value, expected):
    assert parse_homework_state(value) is expected


@pytest.mark.parametrize("value", ["", "XX", "archived", None, 1])
def test_parse_homework_state_rejects_unknown_values(value):
    with pytest.raises(InvalidHomeworkState):
        parse_homework_state(value)


def test_close_homework_persists_and_reports_previous_state():
    hw = make_homework(coursework_cohort())

    change = close_homework(hw)

    assert change.previous_state == HomeworkState.OPEN.value
    assert change.state == HomeworkState.CLOSED.value
    assert change.changed is True
    assert hw.state == HomeworkState.CLOSED.value
    hw.refresh_from_db()
    assert hw.state == HomeworkState.CLOSED.value


def test_set_homework_state_is_a_noop_for_the_current_state():
    hw = make_homework(coursework_cohort(), state=HomeworkState.CLOSED.value)

    change = set_homework_state(hw, "closed")

    assert change.changed is False
    hw.refresh_from_db()
    assert hw.state == HomeworkState.CLOSED.value


def test_set_homework_state_has_no_transition_table():
    """Like CMP, a scored homework can be reopened and an open one marked scored."""

    hw = make_homework(coursework_cohort(), state=HomeworkState.SCORED.value)

    assert set_homework_state(hw, "OP").changed is True
    assert set_homework_state(hw, "SC").changed is True
    hw.refresh_from_db()
    assert hw.state == HomeworkState.SCORED.value


def test_set_homework_state_rejects_unknown_state_without_saving():
    hw = make_homework(coursework_cohort())

    with pytest.raises(InvalidHomeworkState):
        set_homework_state(hw, "archived")

    hw.refresh_from_db()
    assert hw.state == HomeworkState.OPEN.value


def test_set_homework_state_uses_the_locked_row_not_a_stale_instance():
    hw = make_homework(coursework_cohort())
    stale = type(hw).objects.get(pk=hw.pk)
    close_homework(hw)

    change = set_homework_state(stale, "CL")

    assert change.previous_state == HomeworkState.CLOSED.value
    assert change.changed is False


def test_closed_homework_is_refused_by_scoring_until_reopened():
    hw = make_homework(coursework_cohort())
    hw.due_date = hw.due_date.replace(year=hw.due_date.year - 1)
    hw.save(update_fields=["due_date"])
    close_homework(hw)

    status, message = score_homework_submissions(hw.pk)
    assert status.value != "OK"
    assert "closed" in message

    set_homework_state(hw, "open")
    status, _message = score_homework_submissions(hw.pk)
    assert status.value == "OK"


# --- staff bearer API -----------------------------------------------------------


def test_state_api_requires_a_bearer_key(client):
    hw = make_homework(coursework_cohort())

    assert client.get(state_url(hw)).status_code == 401
    assert client.post(state_url(hw, "close")).status_code == 401


def test_state_api_enforces_read_and_write_scopes(client, keys):
    read_key, write_key = keys
    hw = make_homework(coursework_cohort())

    assert client.get(state_url(hw), headers=bearer(write_key)).status_code == 403
    denied = client.post(
        state_url(hw),
        data=json.dumps({"state": "CL"}),
        content_type="application/json",
        headers=bearer(read_key),
    )
    assert denied.status_code == 403
    assert client.post(state_url(hw, "close"), headers=bearer(read_key)).status_code == 403
    hw.refresh_from_db()
    assert hw.state == HomeworkState.OPEN.value


def test_state_api_reads_the_current_state(client, keys):
    read_key, _write_key = keys
    hw = make_homework(coursework_cohort())

    response = client.get(state_url(hw), headers=bearer(read_key))

    assert response.status_code == 200
    assert response.json() == {
        "homework": {
            "id": hw.pk,
            "slug": hw.slug,
            "course_slug": hw.cohort.course.slug,
            "cohort_slug": hw.cohort.slug,
            "state": "OP",
            "state_name": "open",
        }
    }


@pytest.mark.parametrize(("sent", "stored"), [("CL", "CL"), ("scored", "SC"), ("OP", "OP")])
def test_state_api_sets_state_by_code_or_name(client, keys, sent, stored):
    _read_key, write_key = keys
    hw = make_homework(coursework_cohort())

    response = client.post(
        state_url(hw),
        data=json.dumps({"state": sent}),
        content_type="application/json",
        headers=bearer(write_key),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["homework"]["state"] == stored
    assert body["previous_state"] == "OP"
    assert body["changed"] is (stored != "OP")
    hw.refresh_from_db()
    assert hw.state == stored


def test_state_api_rejects_invalid_and_missing_state(client, keys):
    _read_key, write_key = keys
    hw = make_homework(coursework_cohort())

    invalid = client.post(
        state_url(hw),
        data=json.dumps({"state": "archived"}),
        content_type="application/json",
        headers=bearer(write_key),
    )
    missing = client.post(
        state_url(hw),
        data=json.dumps({}),
        content_type="application/json",
        headers=bearer(write_key),
    )

    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_homework_state"
    assert invalid.json()["error"]["details"] == {"valid_states": list(VALID_HOMEWORK_STATES)}
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "missing_field"
    hw.refresh_from_db()
    assert hw.state == HomeworkState.OPEN.value


def test_close_api_closes_and_is_idempotent(client, keys):
    _read_key, write_key = keys
    hw = make_homework(coursework_cohort())

    first = client.post(state_url(hw, "close"), headers=bearer(write_key))
    second = client.post(state_url(hw, "close"), headers=bearer(write_key))

    assert first.status_code == 200
    assert first.json()["changed"] is True
    assert first.json()["homework"]["state_name"] == "closed"
    assert second.status_code == 200
    assert second.json()["changed"] is False
    assert second.json()["previous_state"] == "CL"
    hw.refresh_from_db()
    assert hw.state == HomeworkState.CLOSED.value


def test_state_api_scopes_homework_lookup_to_course_and_cohort(client, keys):
    _read_key, write_key = keys
    hw = make_homework(coursework_cohort())
    wrong_cohort = (
        f"/api/v1/courses/{hw.cohort.course.slug}/cohorts/other/homeworks/{hw.slug}/close"
    )

    response = client.post(wrong_cohort, headers=bearer(write_key))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_homework"
    hw.refresh_from_db()
    assert hw.state == HomeworkState.OPEN.value


# --- Studio action ---------------------------------------------------------------


@pytest.fixture
def staff(client, django_user_model):
    user = django_user_model.objects.create_user(email="studio-state@example.com", is_staff=True)
    client.force_login(user)
    return user


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def test_studio_set_state_closes_and_redirects_to_detail(client, staff):
    hw = make_homework(coursework_cohort())

    response = client.post(
        reverse("coursework_studio_homework_set_state", args=[hw.pk]), {"state": "CL"}
    )

    assert response.status_code == 302
    assert response.url == reverse("coursework_studio_homework_detail", args=[hw.pk])
    assert any("is now closed" in message for message in messages_of(response))
    hw.refresh_from_db()
    assert hw.state == HomeworkState.CLOSED.value


def test_studio_set_state_rejects_invalid_state_and_get(client, staff):
    hw = make_homework(coursework_cohort())
    url = reverse("coursework_studio_homework_set_state", args=[hw.pk])

    invalid = client.post(url, {"state": "archived"})

    assert invalid.status_code == 302
    assert any("Invalid state" in message for message in messages_of(invalid))
    assert client.get(url).status_code == 405
    hw.refresh_from_db()
    assert hw.state == HomeworkState.OPEN.value


def test_studio_set_state_requires_staff(client, django_user_model):
    hw = make_homework(coursework_cohort())
    url = reverse("coursework_studio_homework_set_state", args=[hw.pk])

    anonymous = client.post(url, {"state": "CL"})
    assert anonymous.status_code == 302
    assert anonymous.url.startswith("/accounts/login/")

    client.force_login(django_user_model.objects.create_user(email="member-state@example.com"))
    assert client.post(url, {"state": "CL"}).status_code == 403
    hw.refresh_from_db()
    assert hw.state == HomeworkState.OPEN.value


def test_studio_detail_offers_state_form_and_close_button(client, staff):
    hw = make_homework(coursework_cohort())

    response = client.get(reverse("coursework_studio_homework_detail", args=[hw.pk]))

    content = response.content.decode()
    action = reverse("coursework_studio_homework_set_state", args=[hw.pk])
    assert response.status_code == 200
    assert f'action="{action}"' in content
    assert "Close homework" in content
    assert '<option value="OP" selected>open</option>' in content
