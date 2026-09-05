from django.contrib.auth import get_user_model
from django.db import transaction

from community_base.community.services import (
    get_community_service,
    stale_membership_users,
    sync_membership,
)
from community_base.jobs import dispatch_after_commit, register_handler, schedule


def _user(user_id):
    return get_user_model().objects.filter(pk=user_id).first()


@register_handler("community.slack.invite")
def invite_handler(_context, payload):
    user = _user(payload["user_id"])
    if user is not None:
        get_community_service().invite(user)


@register_handler("community.slack.reactivate")
def reactivate_handler(_context, payload):
    user = _user(payload["user_id"])
    if user is not None:
        get_community_service().reactivate(user)


@register_handler("community.slack.remove")
def remove_handler(_context, payload):
    user = _user(payload["user_id"])
    if user is not None:
        get_community_service().remove(user)


@register_handler("community.slack.check_membership")
def check_membership_handler(_context, payload):
    user = _user(payload["user_id"])
    if user is not None:
        sync_membership(user)


@register_handler("community.slack.refresh_memberships")
def refresh_memberships_handler(_context, _payload):
    service = get_community_service()
    for user in stale_membership_users():
        sync_membership(user, service=service)


def register_schedules():
    schedule(
        "community.slack.refresh_memberships",
        "*/30 * * * *",
        {},
        name="community-base:slack-membership-refresh",
    )


def queue_user_action(action, user, *, key=None, available_at=None):
    if action not in {"invite", "reactivate", "remove", "check_membership"}:
        raise ValueError("unknown community user action")
    if not transaction.get_connection().in_atomic_block:
        raise ValueError("community action dispatch requires an active transaction")
    return dispatch_after_commit(
        f"community.slack.{action}",
        key or f"community:{action}:{user.pk}",
        {"user_id": user.pk},
        available_at=available_at,
    )
