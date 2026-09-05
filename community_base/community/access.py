from django.db import transaction
from django.utils import timezone

from community_base.community.hooks import hooks
from community_base.community.models import SlackAccessGrant
from community_base.kernel import conf
from community_base.mail import send


class CommunityAccessUnavailable(Exception):
    """The member isn't eligible or the invite configuration is incomplete."""


def current_invite_version():
    version = str(conf.get("SLACK_INVITE_VERSION")).strip()
    if not version or len(version) > 64:
        raise CommunityAccessUnavailable("Slack invite version is unavailable")
    return version


def current_invite_url():
    url = str(conf.get("SLACK_INVITE_URL")).strip()
    if not url.startswith("https://") or len(url) > 2048:
        raise CommunityAccessUnavailable("Slack invite URL is unavailable")
    return url


def is_eligible(user):
    return bool(hooks.eligibility(user))


@transaction.atomic
def ensure_access_grant(user, *, source, queue_invite=True):
    """Create or rotate one non-secret grant and optional durable invite."""
    if not is_eligible(user):
        raise CommunityAccessUnavailable("Member isn't eligible for Slack access")
    version = current_invite_version()
    grant, created = SlackAccessGrant.objects.select_for_update().get_or_create(
        user=user,
        defaults={"invite_version": version, "source": source},
    )
    changed = created
    if not created and grant.revoked_at is not None:
        raise CommunityAccessUnavailable("Slack access grant is revoked")
    if not created and grant.invite_version != version:
        grant.invite_version = version
        grant.source = source
        grant.granted_at = timezone.now()
        grant.save(update_fields=("invite_version", "source", "granted_at", "updated_at"))
        changed = True
    delivery = None
    if queue_invite:
        delivery = send(
            "community_invite",
            user.email,
            {"invite_version": version},
            f"community-invite:{user.pk}:{version}",
            user=user,
            related=grant,
        )
    return grant, changed, delivery


@transaction.atomic
def revoke_access(user):
    grant = SlackAccessGrant.objects.select_for_update().filter(user=user).first()
    if grant is None or grant.revoked_at is not None:
        return grant, False
    grant.revoked_at = timezone.now()
    grant.save(update_fields=("revoked_at", "updated_at"))
    return grant, True


@transaction.atomic
def reactivate_access(user, *, source=SlackAccessGrant.Source.OPERATOR):
    if not is_eligible(user):
        raise CommunityAccessUnavailable("Member isn't eligible for Slack access")
    grant = SlackAccessGrant.objects.select_for_update().filter(user=user).first()
    if grant is None:
        return ensure_access_grant(user, source=source)
    changed = grant.revoked_at is not None or grant.invite_version != current_invite_version()
    grant.revoked_at = None
    grant.invite_version = current_invite_version()
    grant.source = source
    grant.granted_at = timezone.now()
    grant.save(update_fields=("revoked_at", "invite_version", "source", "granted_at", "updated_at"))
    delivery = send(
        "community_invite",
        user.email,
        {"invite_version": grant.invite_version},
        f"community-invite:{user.pk}:{grant.invite_version}",
        user=user,
        related=grant,
    )
    return grant, changed, delivery
