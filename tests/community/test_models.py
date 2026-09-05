import pytest
from django.contrib.auth import get_user_model

from community_base.community.models import (
    STATUS_BOOKED,
    BookedCall,
    CallHost,
    CommunityAuditLog,
    SlackAccessGrant,
    is_usable_http_url,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_slack_grant_contains_version_but_no_invite_secret():
    user = get_user_model().objects.create_user(email="member@example.com")
    grant = SlackAccessGrant.objects.create(
        user=user, invite_version="2026-09", source=SlackAccessGrant.Source.ELIGIBILITY
    )

    assert grant.active is True
    assert grant.invite_version == "2026-09"
    assert not hasattr(grant, "invite_url")


def test_call_host_only_exposes_trimmed_http_urls():
    host = CallHost.objects.create(
        name="Host", slug="host", booking_url="https://calendar.example.com/host"
    )

    assert host.is_available is True
    assert host.usable_booking_url == "https://calendar.example.com/host"
    assert is_usable_http_url(" javascript:alert(1)") is False


def test_booked_call_and_safe_audit_use_member_relations():
    user = get_user_model().objects.create_user(email="member@example.com")
    host = CallHost.objects.create(name="Host", slug="host")
    call = BookedCall.objects.create(
        host=host,
        member=user,
        invitee_email="member@example.com",
        calendly_event_uri="https://api.calendly.com/events/one",
    )
    audit = CommunityAuditLog.objects.create(
        user=user, action=CommunityAuditLog.Action.CHECK, details="membership_present"
    )

    assert call.status == STATUS_BOOKED
    assert call.is_active is True
    assert audit.user == user
