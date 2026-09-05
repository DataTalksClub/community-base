from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from community_base.community.access import (
    CommunityAccessUnavailable,
    current_invite_url,
    ensure_access_grant,
)
from community_base.community.models import SlackAccessGrant


def _private(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@never_cache
def slack_access(request):
    try:
        grant, _changed, _delivery = ensure_access_grant(
            request.user,
            source=SlackAccessGrant.Source.ELIGIBILITY,
        )
    except CommunityAccessUnavailable:
        return _private(HttpResponseForbidden("Slack access is unavailable."))
    try:
        invite_url = current_invite_url()
    except CommunityAccessUnavailable:
        invite_url = ""
    return _private(
        render(
            request,
            "community_base/community/slack_access.html",
            {"grant": grant, "invite_url": invite_url},
        )
    )
