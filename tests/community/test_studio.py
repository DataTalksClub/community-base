import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from community_base.community.access import ensure_access_grant
from community_base.community.models import BookedCall, CallHost, SlackAccessGrant

pytestmark = pytest.mark.django_db(transaction=True)


def account(email, **kwargs):
    return get_user_model().objects.create_user(email=email, **kwargs)


def test_member_call_page_is_authenticated_and_feature_gated(client, settings):
    url = reverse("community_base_call_hosts")
    member = account("member@example.com")

    assert client.get(url).status_code == 302
    client.force_login(member)
    settings.COMMUNITY_BASE = {"CALENDLY": False}
    assert client.get(url).status_code == 404


def test_member_call_page_lists_safe_hosts_and_active_booking(client, settings):
    settings.COMMUNITY_BASE = {"CALENDLY": True}
    member = account("member@example.com")
    host = CallHost.objects.create(
        name="Ada",
        slug="ada",
        role_label="Community host",
        booking_url="https://calendly.com/ada/community",
    )
    CallHost.objects.create(name="Unsafe", slug="unsafe", booking_url="javascript:alert(1)")
    BookedCall.objects.create(
        host=host,
        member=member,
        invitee_email=member.email,
        calendly_event_uri="https://api.calendly.com/events/one",
    )
    client.force_login(member)

    response = client.get(reverse("community_base_call_hosts"))

    assert response.status_code == 200
    assert b"https://calendly.com/ada/community" in response.content
    assert b"javascript:" not in response.content
    assert b"Your booked calls" in response.content


def test_community_studio_requires_staff(client):
    member = account("member@example.com")
    client.force_login(member)

    for name in (
        "community_studio_access_list",
        "community_studio_audit_list",
        "community_studio_call_host_list",
        "community_studio_booked_call_list",
        "community_studio_unmatched_call_list",
    ):
        assert client.get(reverse(name)).status_code == 403


def test_access_studio_never_projects_invite_url(client, settings):
    secret = "https://join.slack.com/private-secret"
    settings.COMMUNITY_BASE = {
        "JOBS_BACKEND": "sync",
        "MAIL_BACKEND": "memory",
        "SLACK_INVITE_URL": secret,
        "SLACK_INVITE_VERSION": "v1",
    }
    staff = account("staff@example.com", is_staff=True, email_verified=True)
    ensure_access_grant(staff, source=SlackAccessGrant.Source.OPERATOR)
    client.force_login(staff)

    response = client.get(reverse("community_studio_access_list"))

    assert response.status_code == 200
    assert b"version v1" in response.content
    assert secret.encode() not in response.content


def test_staff_can_create_and_edit_call_host(client):
    staff = account("staff@example.com", is_staff=True)
    client.force_login(staff)
    create_url = reverse("community_studio_call_host_create")

    response = client.post(
        create_url,
        {
            "name": "Ada",
            "slug": "ada",
            "role_label": "Community host",
            "photo_url": "",
            "booking_url": "https://calendly.com/ada/community",
            "is_active": "on",
            "capacity": 4,
            "order": 1,
        },
    )

    host = CallHost.objects.get(slug="ada")
    assert response.status_code == 302
    response = client.post(
        reverse("community_studio_call_host_edit", args=(host.pk,)),
        {
            "name": "Ada Updated",
            "slug": "ada",
            "role_label": "Community host",
            "photo_url": "",
            "booking_url": "https://calendly.com/ada/community",
            "is_active": "on",
            "capacity": 5,
            "order": 1,
        },
    )
    host.refresh_from_db()
    assert response.status_code == 302
    assert host.name == "Ada Updated"
    assert host.current_load == 0
