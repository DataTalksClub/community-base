from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from community_base.mail import relay_links
from community_base.mail.relay_links import TRANSPARENT_GIF, BridgeOutcome
from community_base.mail.unsubscribe import accept_unsubscribe_for_replay

logger = logging.getLogger(__name__)
_SCOPE_LABELS = {
    "client": "Stop marketing email from this community",
    "audience": "Stop email from this list only",
    "global": "Stop every marketing email we send",
}


def _record_degradation(route: str, outcome: BridgeOutcome) -> None:
    if outcome is BridgeOutcome.RECORDED:
        return
    logger.info(
        "relay_link_bridge_degraded",
        extra={"route": route, "outcome": outcome.value},
    )


def _seal(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    request.private_response_required = True  # type: ignore[attr-defined]
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow"
    if response.status_code >= 400:
        response._has_been_logged = True  # type: ignore[attr-defined]
    return response


def _gif(request: HttpRequest, *, status: int) -> HttpResponse:
    response = HttpResponse(TRANSPARENT_GIF, status=status, content_type="image/gif")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Content-Length"] = str(len(TRANSPARENT_GIF))
    return _seal(request, response)


@require_GET
def tracking_open(request: HttpRequest, tracking_token: str) -> HttpResponse:
    result = relay_links.record_open(tracking_token)
    if result.outcome in {BridgeOutcome.NOT_CONFIGURED, BridgeOutcome.REJECTED}:
        return _gif(request, status=404)
    return _gif(request, status=200)


@require_GET
def tracking_click(request: HttpRequest, tracking_token: str) -> HttpResponse:
    destination = request.GET.get("u", "")
    safe_destination = destination if relay_links.is_safe_click_destination(destination) else ""
    if not relay_links.is_configured():
        _record_degradation("click", BridgeOutcome.NOT_CONFIGURED)
        return _click_notice(request, status=404, destination="")
    if not safe_destination:
        _record_degradation("click", BridgeOutcome.INVALID)
        return _click_notice(request, status=400, destination="")
    result = relay_links.record_click(tracking_token, safe_destination)
    _record_degradation("click", result.outcome)
    if result.outcome is BridgeOutcome.RECORDED:
        return _seal(request, HttpResponseRedirect(safe_destination))
    if result.answered:
        return _click_notice(request, status=400, destination=safe_destination)
    return _click_notice(
        request,
        status=200,
        destination=safe_destination,
        unavailable=True,
    )


def _click_notice(
    request: HttpRequest,
    *,
    status: int,
    destination: str,
    unavailable: bool = False,
) -> HttpResponse:
    return _seal(
        request,
        render(
            request,
            "community_base/mail/click_notice.html",
            {"destination": destination, "unavailable": unavailable},
            status=status,
        ),
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def public_unsubscribe(request: HttpRequest, unsubscribe_token: str) -> HttpResponse:
    if not relay_links.is_configured():
        _record_degradation("unsubscribe", BridgeOutcome.NOT_CONFIGURED)
        return _render_unsubscribe(request, state="unknown", status=404)
    if request.method == "POST":
        return _apply_unsubscribe(request, unsubscribe_token)
    result = relay_links.load_unsubscribe(unsubscribe_token)
    _record_degradation("unsubscribe", result.outcome)
    if result.outcome is BridgeOutcome.REJECTED:
        return _render_unsubscribe(request, state="unknown", status=404)
    return _render_unsubscribe(
        request,
        state="form",
        status=200,
        degraded=not result.answered,
    )


def _apply_unsubscribe(request: HttpRequest, token: str) -> HttpResponse:
    scope = request.POST.get("scope", "")
    if scope not in relay_links.UNSUBSCRIBE_SCOPES:
        return _render_unsubscribe(request, state="form", status=400, invalid_scope=True)
    result = relay_links.submit_unsubscribe(token, scope)
    _record_degradation("unsubscribe", result.outcome)
    if result.outcome is BridgeOutcome.RECORDED:
        return _render_unsubscribe(request, state="confirmed", status=200, scope=scope)
    if result.outcome is BridgeOutcome.REJECTED:
        return _render_unsubscribe(request, state="unknown", status=404)
    if result.outcome is BridgeOutcome.INVALID:
        return _render_unsubscribe(request, state="form", status=400, invalid_scope=True)
    try:
        accept_unsubscribe_for_replay(token=token, scope=scope)
    except ValueError:
        return _render_unsubscribe(request, state="unknown", status=404)
    return _render_unsubscribe(request, state="accepted", status=202, scope=scope)


def _render_unsubscribe(
    request: HttpRequest,
    *,
    state: str,
    status: int,
    scope: str = "",
    degraded: bool = False,
    invalid_scope: bool = False,
) -> HttpResponse:
    return _seal(
        request,
        render(
            request,
            "community_base/mail/unsubscribe.html",
            {
                "state": state,
                "degraded": degraded,
                "invalid_scope": invalid_scope,
                "chosen_scope": scope,
                "scope_choices": tuple(_SCOPE_LABELS.items()),
            },
            status=status,
        ),
    )
