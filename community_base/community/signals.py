from django.dispatch import receiver

from community_base.community.access import CommunityAccessUnavailable, ensure_access_grant
from community_base.community.models import SlackAccessGrant
from community_base.onboarding.signals import onboarding_completed


@receiver(onboarding_completed, dispatch_uid="community_base.community.onboarding_completed")
def grant_after_onboarding(sender, user, flow, **kwargs):
    try:
        ensure_access_grant(user, source=SlackAccessGrant.Source.ONBOARDING)
    except CommunityAccessUnavailable:
        return
