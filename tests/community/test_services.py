import pytest
from django.contrib.auth import get_user_model

from community_base.community.import_slack import slack_import_rows
from community_base.community.models import CommunityAuditLog, SlackAccessGrant
from community_base.community.services import (
    SlackAPIError,
    SlackCommunityService,
    sync_membership,
)
from community_base.mail.models import EmailDelivery

pytestmark = pytest.mark.django_db(transaction=True)


class Response:
    def __init__(self, data=None, *, status=200, headers=None, invalid_json=False):
        self.data = data or {}
        self.status_code = status
        self.headers = headers or {}
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError
        return self.data


def configured(settings, **overrides):
    settings.COMMUNITY_BASE = {
        "JOBS_BACKEND": "sync",
        "MAIL_BACKEND": "memory",
        "SLACK_ENABLED": True,
        "SLACK_BOT_TOKEN": "secret-token",
        "SLACK_INVITE_VERSION": "v1",
        "SLACK_COMMUNITY_CHANNEL_IDS": ["C1", "C2"],
        **overrides,
    }


def user(email="member@example.com", **kwargs):
    return get_user_model().objects.create_user(email=email, email_verified=True, **kwargs)


def test_api_call_uses_bearer_token_without_exposing_it_in_errors(settings):
    configured(settings)
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"ok": False, "error": "missing_scope"})

    service = SlackCommunityService(request=request)

    with pytest.raises(SlackAPIError, match="missing_scope") as raised:
        service.lookup_user_by_email("member@example.com")

    assert "secret-token" not in str(raised.value)
    assert calls[0][0].endswith("/users.lookupByEmail")
    assert calls[0][1]["headers"]["Authorization"] == "Bearer secret-token"


def test_api_call_retries_rate_limit_once_and_caps_delay(settings):
    configured(settings)
    responses = iter(
        [
            Response(status=429, headers={"Retry-After": "90"}),
            Response(status=429),
        ]
    )
    delays = []
    service = SlackCommunityService(
        request=lambda *args, **kwargs: next(responses), sleep=delays.append
    )

    with pytest.raises(SlackAPIError, match="ratelimited"):
        service.lookup_user_by_email("member@example.com")

    assert delays == [30]


def test_channel_updates_continue_and_treat_existing_membership_as_success(settings):
    configured(settings)
    responses = iter(
        [
            Response({"ok": False, "error": "already_in_channel"}),
            Response({"ok": False, "error": "channel_not_found"}),
        ]
    )
    service = SlackCommunityService(request=lambda *args, **kwargs: next(responses))

    assert service.add_to_channels("U1") == [
        {"channel": "C1", "ok": True, "error": ""},
        {"channel": "C2", "ok": False, "error": "channel_not_found"},
    ]


def test_invite_links_member_grants_access_and_writes_safe_audit(settings):
    configured(settings)
    responses = iter(
        [
            Response({"ok": True, "user": {"id": "U1"}}),
            Response({"ok": True}),
            Response({"ok": True}),
        ]
    )
    member = user()
    service = SlackCommunityService(request=lambda *args, **kwargs: next(responses))

    grant, delivery, results = service.invite(member)

    member.refresh_from_db()
    assert member.slack_user_id == "U1"
    assert grant.source == SlackAccessGrant.Source.ELIGIBILITY
    assert delivery == EmailDelivery.objects.get()
    assert all(result["ok"] for result in results)
    audit = CommunityAuditLog.objects.get(action=CommunityAuditLog.Action.INVITE)
    assert "U1" in audit.details
    assert "secret-token" not in audit.details


def test_invite_still_grants_and_queues_mail_when_slack_api_is_disabled(settings):
    configured(settings, SLACK_ENABLED=False)
    member = user()

    grant, delivery, results = SlackCommunityService().invite(member)

    assert grant.active is True
    assert delivery == EmailDelivery.objects.get()
    assert results == []


def test_membership_unknown_preserves_state_and_member_refreshes_it(settings):
    configured(settings)
    member = user(slack_member=True, slack_user_id="")

    class Service:
        def check_workspace_membership(self, email):
            return "unknown", None

    assert sync_membership(member, service=Service()) == "unknown"
    member.refresh_from_db()
    assert member.slack_member is True
    assert member.slack_checked_at is None

    class FoundService:
        def check_workspace_membership(self, email):
            return "member", "U1"

    assert sync_membership(member, service=FoundService()) == "member"
    member.refresh_from_db()
    assert member.slack_user_id == "U1"
    assert member.slack_checked_at is not None


def test_import_rows_paginate_filter_and_map_slack_identity(settings):
    configured(settings)

    class Service:
        def iter_workspace_members(self):
            yield {"id": "BOT", "is_bot": True, "profile": {"email": "bot@example.com"}}
            yield {"id": "NOEMAIL", "profile": {}}
            yield {
                "id": "U1",
                "team_id": "T1",
                "tz": "Europe/London",
                "is_admin": True,
                "profile": {
                    "email": "ada@example.com",
                    "real_name_normalized": "Ada Lovelace",
                },
            }

    rows = list(slack_import_rows(service=Service()))

    assert len(rows) == 2
    assert rows[0] == {"email": "", "metadata": {"slack_id": "NOEMAIL"}}
    assert rows[1].email == "ada@example.com"
    assert rows[1].first_name == "Ada"
    assert rows[1].last_name == "Lovelace"
    assert rows[1].tags == ("slack-member", "slack-admin")
    assert rows[1].fields == {
        "slack_user_id": "U1",
        "slack_member": True,
        "preferred_timezone": "Europe/London",
    }
    assert rows[1].metadata == {"slack_id": "U1", "slack_team_id": "T1"}


def test_workspace_members_follow_all_slack_pages(settings):
    configured(settings)
    calls = []
    responses = iter(
        [
            Response(
                {
                    "ok": True,
                    "members": [{"id": "U1"}],
                    "response_metadata": {"next_cursor": "next"},
                }
            ),
            Response({"ok": True, "members": [{"id": "U2"}]}),
        ]
    )

    def request(_url, **kwargs):
        calls.append(kwargs["json"])
        return next(responses)

    service = SlackCommunityService(request=request)

    assert list(service.iter_workspace_members()) == [{"id": "U1"}, {"id": "U2"}]
    assert calls == [
        {"limit": 200, "cursor": ""},
        {"limit": 200, "cursor": "next"},
    ]
