import json

import pytest
from django.contrib.auth import get_user_model

from community_base.accounts.models import MemberProfile, PrivacyRequestLog

pytestmark = pytest.mark.django_db(transaction=True)


def _profile_payload(**overrides):
    values = {
        "country": "de",
        "work_status": "employed",
        "organisation": "Data Community",
        "professional_role": "data_engineer",
        "seniority": "mid",
        "about": "I build data platforms.",
        "ambitions": "Help more people learn.",
        "why_joined": "To contribute and learn.",
        "github_url": "https://github.com/member",
        "linkedin_url": "",
        "website_url": "https://example.com/profile",
    }
    values.update(overrides)
    return values


def test_self_api_requires_the_signed_in_member(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me/profile").status_code == 401


def test_me_returns_only_the_signed_in_account(client):
    member = get_user_model().objects.create_user(
        email="member@example.com",
        first_name="Ada",
        email_preferences={"events": False},
    )
    get_user_model().objects.create_user(email="other@example.com")
    client.force_login(member)

    response = client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["account"]["id"] == member.pk
    assert response.json()["account"]["email"] == "member@example.com"
    assert "password" not in response.json()["account"]
    assert set(response["Cache-Control"].split(", ")) == {
        "max-age=0",
        "no-cache",
        "no-store",
        "private",
    }


def test_me_patch_updates_owned_preferences_timezone_and_dismissal(client):
    member = get_user_model().objects.create_user(email="member@example.com")
    other = get_user_model().objects.create_user(email="other@example.com")
    client.force_login(member)

    response = client.patch(
        "/api/v1/me",
        data=json.dumps(
            {
                "first_name": " Ada ",
                "email_preferences": {"newsletter": False, "events": True},
                "preferred_timezone": "Europe/Berlin",
                "theme_preference": "dark",
                "dismiss_card": "getting_started:events",
            }
        ),
        content_type="application/json",
    )

    member.refresh_from_db()
    other.refresh_from_db()
    assert response.status_code == 200
    assert member.first_name == "Ada"
    assert member.unsubscribed is True
    assert member.email_preferences == {"newsletter": False, "events": True}
    assert member.preferred_timezone == "Europe/Berlin"
    assert member.theme_preference == "dark"
    assert member.dashboard_dismissals == ["getting_started:events"]
    assert other.first_name == ""


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"is_staff": True},
        {"email_preferences": {"events": "yes"}},
        {"preferred_timezone": "Mars/Olympus"},
        {"theme_preference": "sepia"},
        {"dismiss_card": "../../unsafe"},
    ],
)
def test_me_patch_rejects_empty_unknown_and_invalid_updates(client, payload):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)

    response = client.patch(
        "/api/v1/me",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 400


def test_password_change_checks_current_password_and_preserves_session(client):
    member = get_user_model().objects.create_user(
        email="member@example.com", password="old-password"
    )
    client.force_login(member)

    rejected = client.post(
        "/api/v1/me/password",
        data=json.dumps({"current_password": "wrong", "new_password": "new-password"}),
        content_type="application/json",
    )
    changed = client.post(
        "/api/v1/me/password",
        data=json.dumps({"current_password": "old-password", "new_password": "new-password"}),
        content_type="application/json",
    )

    member.refresh_from_db()
    assert rejected.status_code == 400
    assert changed.status_code == 200
    assert member.check_password("new-password")
    assert member.account_activated is True
    assert client.get("/api/v1/me").status_code == 200


def test_privacy_export_and_deletion_request_are_member_owned(client):
    member = get_user_model().objects.create_user(email="member@example.com")
    other = get_user_model().objects.create_user(email="other@example.com")
    client.force_login(member)

    exported = client.get("/api/v1/me/data-export")
    requested = client.post(
        "/api/v1/me/deletion-request",
        data="{}",
        content_type="application/json",
    )
    repeated = client.post(
        "/api/v1/me/deletion-request",
        data="{}",
        content_type="application/json",
    )

    assert exported.status_code == 200
    assert exported.json()["account"]["email"] == member.email
    assert other.email not in exported.content.decode()
    assert exported["Content-Disposition"].startswith("attachment;")
    assert requested.status_code == 201
    assert repeated.status_code == 200
    assert PrivacyRequestLog.objects.filter(old_user_id=member.pk).count() == 2
    assert PrivacyRequestLog.objects.filter(old_user_id=other.pk).count() == 0


def test_account_page_uses_package_template_contract(client):
    member = get_user_model().objects.create_user(email="member@example.com")

    anonymous = client.get("/accounts/account/")
    client.force_login(member)
    response = client.get("/accounts/account/")

    assert anonymous.status_code == 302
    assert response.status_code == 200
    assert {"private", "no-cache", "no-store", "max-age=0"} == set(
        response["Cache-Control"].split(", ")
    )
    assert b'<main class="cb-page">' in response.content
    assert b'data-cb-api-form="/api/v1/me/profile"' in response.content
    assert b'id="email-preferences"' in response.content
    assert b'id="change-password"' in response.content
    assert b'id="privacy-data"' in response.content


def test_profile_get_is_private_and_does_not_create_a_row(client):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)

    response = client.get("/api/v1/me/profile")

    assert response.status_code == 200
    assert response["ETag"] == '"rev-0"'
    assert response.json()["profile"]["id"] is None
    assert response.json()["profile"]["revision"] == 0
    assert response.json()["profile"]["missing_fields"]
    assert MemberProfile.objects.count() == 0


def test_profile_patch_completes_verified_profile_and_rejects_stale_write(client):
    member = get_user_model().objects.create_user(
        email="member@example.com",
        email_verified=True,
    )
    client.force_login(member)

    response = client.patch(
        "/api/v1/me/profile",
        data=json.dumps(_profile_payload()),
        content_type="application/json",
        headers={"If-Match": '"rev-0"'},
    )
    stale = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"about": "Stale overwrite"}),
        content_type="application/json",
        headers={"If-Match": '"rev-0"'},
    )

    assert response.status_code == 200
    assert response["ETag"] == '"rev-1"'
    assert response.json()["profile"]["country"] == "DE"
    assert response.json()["profile"]["completion_version"] == 1
    assert response.json()["profile"]["missing_fields"] == []
    assert stale.status_code == 409
    assert stale.json()["error"]["details"] == {"current_revision": 1}
    assert MemberProfile.objects.get(user=member).about == "I build data platforms."


@pytest.mark.parametrize("header", [None, 'W/"rev-0"', "*", '"rev-01"', '"other-0"'])
def test_profile_patch_requires_one_strong_revision(client, header):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)
    headers = {} if header is None else {"If-Match": header}

    response = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"about": "A partial profile"}),
        content_type="application/json",
        headers=headers,
    )

    assert response.status_code == (428 if header is None else 400)
    assert MemberProfile.objects.count() == 0


def test_profile_patch_is_allowlisted_and_validated(client):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)

    unknown = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"revision": 99}),
        content_type="application/json",
        headers={"If-Match": '"rev-0"'},
    )
    unsafe_url = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"website_url": "javascript:alert(1)"}),
        content_type="application/json",
        headers={"If-Match": '"rev-0"'},
    )

    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "unknown_fields"
    assert unsafe_url.status_code == 400
    assert unsafe_url.json()["error"]["code"] == "invalid_profile"
    assert MemberProfile.objects.count() == 0


def test_completed_profile_cannot_clear_a_required_value(client):
    member = get_user_model().objects.create_user(email="member@example.com", email_verified=True)
    profile = MemberProfile.objects.create(
        user=member,
        completion_version=1,
        revision=4,
        confirmed_revision=4,
        **_profile_payload(),
    )
    client.force_login(member)

    response = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"about": ""}),
        content_type="application/json",
        headers={"If-Match": '"rev-4"'},
    )

    profile.refresh_from_db()
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "required_fields_missing"
    assert profile.about == "I build data platforms."


def test_unverified_profile_waits_for_verification_and_completion_is_preserved(client):
    member = get_user_model().objects.create_user(email="member@example.com")
    client.force_login(member)
    first = client.patch(
        "/api/v1/me/profile",
        data=json.dumps(_profile_payload()),
        content_type="application/json",
        headers={"If-Match": '"rev-0"'},
    )
    profile = MemberProfile.objects.get(user=member)
    assert first.status_code == 200
    assert profile.completion_version == 0
    assert profile.completed_at is None

    member.email_verified = True
    member.save(update_fields=["email_verified"])
    completed = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"organisation": "Updated organization"}),
        content_type="application/json",
        headers={"If-Match": '"rev-1"'},
    )
    profile.refresh_from_db()
    completed_at = profile.completed_at
    assert completed.status_code == 200
    assert profile.completion_version == 1
    assert completed_at is not None

    edited = client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"about": "An ordinary valid edit."}),
        content_type="application/json",
        headers={"If-Match": '"rev-2"'},
    )
    profile.refresh_from_db()
    assert edited.status_code == 200
    assert profile.completion_version == 1
    assert profile.completed_at == completed_at
    assert profile.confirmed_revision == profile.revision == 3


def test_member_setting_collections_are_bounded(client):
    member = get_user_model().objects.create_user(
        email="member@example.com",
        email_preferences={f"preference_{index}": True for index in range(100)},
        dashboard_dismissals=[f"card_{index}" for index in range(100)],
    )
    client.force_login(member)

    preferences = client.patch(
        "/api/v1/me",
        data=json.dumps({"email_preferences": {"one_more": True}}),
        content_type="application/json",
    )
    dismissal = client.patch(
        "/api/v1/me",
        data=json.dumps({"dismiss_card": "one_more"}),
        content_type="application/json",
    )

    assert preferences.status_code == 400
    assert preferences.json()["error"]["code"] == "too_many_email_preferences"
    assert dismissal.status_code == 400
    assert dismissal.json()["error"]["code"] == "too_many_dismissals"


def test_profile_patch_is_csrf_protected():
    from django.test import Client

    member = get_user_model().objects.create_user(email="member@example.com")
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(member)

    response = csrf_client.patch(
        "/api/v1/me/profile",
        data=json.dumps({"about": "No CSRF token"}),
        content_type="application/json",
        headers={"If-Match": '"rev-0"'},
    )

    assert response.status_code == 403
    assert MemberProfile.objects.count() == 0
