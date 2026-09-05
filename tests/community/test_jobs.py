from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from community_base.community.jobs import queue_user_action
from community_base.community.services import stale_membership_users, sync_membership
from community_base.community.slack_links import build_slack_profile_url
from community_base.jobs.registry import registered_handler_names, registered_schedules

pytestmark = pytest.mark.django_db(transaction=True)


def member(email, **kwargs):
    kwargs.setdefault("email_verified", True)
    return get_user_model().objects.create_user(email=email, **kwargs)


def test_community_handlers_and_bounded_refresh_schedule_are_registered():
    assert {
        "community.slack.invite",
        "community.slack.reactivate",
        "community.slack.remove",
        "community.slack.check_membership",
        "community.slack.refresh_memberships",
    }.issubset(registered_handler_names())
    schedules = {item.name: item for item in registered_schedules()}
    refresh = schedules["community-base:slack-membership-refresh"]
    assert refresh.handler == "community.slack.refresh_memberships"
    assert refresh.cron == "*/30 * * * *"
    assert refresh.payload == {}


def test_queue_action_persists_only_opaque_user_id(settings):
    settings.COMMUNITY_BASE = {"JOBS_BACKEND": "sync"}
    user = member("private@example.com")

    with transaction.atomic():
        intent, created = queue_user_action(
            "check_membership",
            user,
            available_at=timezone.now() + timedelta(hours=1),
        )

    assert created is True
    assert intent.payload == {"user_id": user.pk}
    assert "private@example.com" not in repr(intent.__dict__)


def test_stale_membership_selection_honors_eligibility_and_batch(settings):
    settings.COMMUNITY_BASE = {
        "COMMUNITY_ELIGIBILITY": lambda user: user.email_verified,
        "SLACK_MEMBERSHIP_BATCH_SIZE": 1,
        "SLACK_MEMBERSHIP_REFRESH_DAYS": 7,
    }
    first = member("first@example.com")
    member("second@example.com")
    member("ineligible@example.com", email_verified=False)
    fresh = member("fresh@example.com")
    fresh.slack_checked_at = timezone.now()
    fresh.save(update_fields=("slack_checked_at",))

    assert stale_membership_users() == [first]


def test_membership_sync_mirrors_tag_and_emits_transition_hook(settings):
    joined = []
    settings.COMMUNITY_BASE = {"COMMUNITY_JOINED_HOOK": lambda **kwargs: joined.append(kwargs)}
    user = member("joined@example.com", slack_checked_at=timezone.now())

    class JoinedService:
        def check_workspace_membership(self, email):
            return "member", "U123"

    class LeftService:
        def check_workspace_membership(self, email):
            return "not_member", None

    assert sync_membership(user, service=JoinedService()) == "member"
    user.refresh_from_db()
    assert user.tags == ["slack-member"]
    assert joined == [{"user": user}]

    assert sync_membership(user, service=LeftService()) == "not_member"
    user.refresh_from_db()
    assert user.tags == []


def test_slack_profile_link_requires_valid_workspace_and_user_ids(settings):
    settings.COMMUNITY_BASE = {"SLACK_TEAM_ID": "T123ABC"}

    assert build_slack_profile_url("U456DEF") == ("https://app.slack.com/client/T123ABC/U456DEF")
    assert build_slack_profile_url("../secret") == ""
    assert build_slack_profile_url("U456DEF", "https://invalid") == ""
