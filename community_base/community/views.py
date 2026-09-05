import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from community_base.community.access import (
    CommunityAccessUnavailable,
    current_invite_url,
    ensure_access_grant,
)
from community_base.community.calendly import process_webhook, verify_signature, webhook_max_bytes
from community_base.community.models import SlackAccessGrant
from community_base.kernel import conf


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


@csrf_exempt
@require_POST
def calendly_webhook(request):
    if not conf.get("CALENDLY"):
        raise Http404
    body = request.body
    if len(body) > webhook_max_bytes():
        return HttpResponseBadRequest("Invalid webhook")
    signature = request.headers.get("Calendly-Webhook-Signature", "")
    if not verify_signature(body, signature):
        return HttpResponseBadRequest("Invalid webhook")
    try:
        payload = json.loads(body)
    except (TypeError, ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("Invalid webhook")
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("Invalid webhook")
    process_webhook(payload)
    return JsonResponse({"ok": True})
