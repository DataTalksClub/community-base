"""Anonymous device endpoints plus the session approval surface.

Wire (RFC 8628-shaped, flat `{"error": code}` errors, all slashless):

- POST /api/auth/device -> start, anonymous
- POST /api/auth/device/token -> poll, anonymous, device_code is the credential
- GET /api/auth/device/pending?user_code= -> session facts for the review page
- POST /api/auth/device/approve -> session decision, admin only

Grants are single use: the first approved poll mints and consumes the
grant; denied, expired, consumed and unknown grants are indistinguishable
on the poll wire (`expired_token`), except a denial is reported once as
`access_denied`.
"""

from __future__ import annotations

import json

from django.conf import settings as django_settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from community_base.device_login import rate_limit
from community_base.device_login.codes import (
    format_user_code,
    generate_device_code,
    generate_user_code,
    is_valid_user_code,
    normalize_user_code,
    sanitize_label,
    sha256_hex,
)
from community_base.device_login.hooks import is_device_admin, mint_device_credential
from community_base.device_login.models import DeviceGrant, DeviceGrantStatus
from community_base.kernel.conf import get

ATTEMPT_BUDGET = 5


def _json_error(code: str, message: str, *, status: int = 400, headers=None) -> JsonResponse:
    response = JsonResponse({"error": code, "message": message}, status=status)
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def _read_json_object(request) -> dict:
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _client_ip(request) -> str:
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def _consume(grant: DeviceGrant) -> None:
    grant.delete()


def _expired(grant: DeviceGrant | None) -> JsonResponse:
    if grant is not None:
        _consume(grant)
    return _json_error("expired_token", "The code expired. Run login again.")


def _verification_uris(request, compact: str) -> tuple[str, str]:
    base = request.build_absolute_uri(reverse("community_device_login_page"))
    return base, f"{base}?code={format_user_code(compact)}"


@csrf_exempt
@require_POST
def device_start(request):
    allowed, retry_after = rate_limit.check_budget(
        prefix="start",
        ip=_client_ip(request),
        limit=rate_limit.START_LIMIT,
        window=rate_limit.START_WINDOW_SECONDS,
    )
    if not allowed:
        return _json_error(
            "slow_down",
            "Too many login attempts. Wait and try again.",
            status=429,
            headers={"Retry-After": str(retry_after)},
        )
    payload = _read_json_object(request)
    label = sanitize_label(payload.get("label"))
    ttl = int(get("DEVICE_LOGIN_TTL_SECONDS"))
    interval = int(get("DEVICE_LOGIN_POLL_INTERVAL"))
    for _ in range(5):
        user_code = generate_user_code()
        compact = normalize_user_code(user_code)
        device_code = generate_device_code()
        if (
            DeviceGrant.objects.filter(device_code_hash=sha256_hex(device_code)).exists()
            or DeviceGrant.objects.filter(user_code_hash=sha256_hex(compact or "")).exists()
        ):
            continue
        DeviceGrant.objects.create(
            device_code_hash=sha256_hex(device_code),
            user_code_hash=sha256_hex(compact or ""),
            label=label,
            request_ip=_client_ip(request),
            expires_at=timezone.now() + timezone.timedelta(seconds=ttl),
        )
        verification_uri, verification_uri_complete = _verification_uris(request, compact or "")
        return JsonResponse(
            {
                "device_code": device_code,
                "user_code": user_code,
                "verification_uri": verification_uri,
                "verification_uri_complete": verification_uri_complete,
                "expires_in": ttl,
                "interval": interval,
            }
        )
    return _json_error("slow_down", "Too many login attempts. Wait and try again.", status=429)


@csrf_exempt
@require_POST
def device_token(request):
    allowed, retry_after = rate_limit.check_budget(
        prefix="poll",
        ip=_client_ip(request),
        limit=rate_limit.POLL_LIMIT,
        window=rate_limit.POLL_WINDOW_SECONDS,
    )
    if not allowed:
        return _json_error(
            "slow_down",
            "Polling too fast. Slow down.",
            status=429,
            headers={"Retry-After": str(retry_after)},
        )
    payload = _read_json_object(request)
    device_code = (payload.get("device_code") or "").strip()
    if not device_code:
        return _json_error("invalid_request", "A device_code is required.")
    grant = DeviceGrant.objects.filter(device_code_hash=sha256_hex(device_code)).first()
    if grant is None:
        return _json_error("expired_token", "The code expired. Run login again.")
    if grant.is_expired:
        return _expired(grant)
    interval = int(get("DEVICE_LOGIN_POLL_INTERVAL"))
    now = timezone.now()
    if grant.last_poll_at and (now - grant.last_poll_at).total_seconds() < max(interval - 1, 0):
        grant.last_poll_at = now
        grant.save(update_fields=["last_poll_at"])
        return _json_error("slow_down", "Polling too fast. Slow down.")
    grant.last_poll_at = now
    grant.save(update_fields=["last_poll_at"])
    if grant.status == DeviceGrantStatus.DENIED:
        _consume(grant)
        return _json_error("access_denied", "The login was denied in the browser.")
    if grant.status != DeviceGrantStatus.APPROVED:
        return _json_error("authorization_pending", "Waiting for browser approval.")
    with transaction.atomic():
        locked = DeviceGrant.objects.select_for_update().filter(pk=grant.pk).first()
        if locked is None or locked.status != DeviceGrantStatus.APPROVED or locked.is_expired:
            return _expired(locked)
        user = locked.approved_by
        if user is None or not is_device_admin(user):
            _consume(locked)
            return _json_error("access_denied", "The login was denied in the browser.")
        label = locked.label
        credential = mint_device_credential(user=user, label=label, request=request)
        _consume(locked)
    return JsonResponse(credential)


def _grant_for_user_code(value: str | None) -> DeviceGrant | None:
    compact = normalize_user_code(value)
    if compact is None:
        return None
    return DeviceGrant.objects.filter(user_code_hash=sha256_hex(compact)).first()


def _spend_attempt(grant: DeviceGrant) -> bool:
    """Count one lookup/decision. Returns False when the budget is spent."""
    grant.attempts += 1
    if grant.attempts > ATTEMPT_BUDGET:
        _consume(grant)
        return False
    grant.save(update_fields=["attempts"])
    return True


def _require_session(request):
    if not request.user.is_authenticated:
        return _json_error("authentication_required", "Sign in to approve this device.", status=401)
    return None


@never_cache
def device_pending(request):
    session_error = _require_session(request)
    if session_error is not None:
        return session_error
    grant = _grant_for_user_code(request.GET.get("user_code") or request.GET.get("userCode"))
    if grant is None or grant.is_expired:
        return _json_error("invalid_code", "That code is not waiting for confirmation.", status=404)
    if not _spend_attempt(grant):
        return _json_error("invalid_code", "That code is not waiting for confirmation.", status=404)
    if grant.status != DeviceGrantStatus.PENDING:
        return _json_error("invalid_code", "That code is not waiting for confirmation.", status=404)
    return JsonResponse(
        {
            "label": grant.label,
            "request_ip": grant.request_ip,
            "created_at": grant.created_at.isoformat(),
            "expires_at": grant.expires_at.isoformat(),
            "server_now": timezone.now().isoformat(),
        }
    )


@csrf_exempt
@require_POST
def device_approve(request):
    session_error = _require_session(request)
    if session_error is not None:
        return session_error
    payload = _read_json_object(request)
    raw_code = payload.get("user_code", payload.get("userCode", ""))
    grant = _grant_for_user_code(raw_code)
    if grant is None or grant.is_expired:
        return _json_error("invalid_code", "That code is not waiting for confirmation.", status=404)
    if not _spend_attempt(grant):
        return _json_error("invalid_code", "That code is not waiting for confirmation.", status=404)
    if grant.status != DeviceGrantStatus.PENDING:
        return _json_error("invalid_code", "That code is not waiting for confirmation.", status=404)
    if not is_device_admin(request.user):
        return JsonResponse(
            {"error": "admin_only", "message": "Only admins can approve a device login."},
            status=403,
        )
    approve = payload.get("approve", True)
    grant.status = DeviceGrantStatus.APPROVED if approve else DeviceGrantStatus.DENIED
    grant.approved_by = request.user if approve else None
    grant.decided_at = timezone.now()
    grant.save(update_fields=["status", "approved_by", "decided_at"])
    return JsonResponse({"status": "approved" if approve else "denied", "label": grant.label})


@never_cache
def device_page(request):
    if not request.user.is_authenticated:
        login_url = str(getattr(django_settings, "LOGIN_URL", "/accounts/login/"))
        return redirect(f"{login_url}?next={request.get_full_path()}")
    context = {
        "code": "",
        "facts": None,
        "error": "",
        "result": "",
        "is_admin": is_device_admin(request.user),
    }
    if request.method == "POST":
        action = request.POST.get("action", "lookup")
        code = request.POST.get("user_code", "")
        context["code"] = code
        if not is_valid_user_code(code):
            context["error"] = "Enter the 8-character code shown by the CLI."
            return render(request, "community_base/device_login/device.html", context)
        grant = _grant_for_user_code(code)
        if grant is None or grant.is_expired or grant.status != DeviceGrantStatus.PENDING:
            context["error"] = "That code is not waiting for confirmation."
            return render(request, "community_base/device_login/device.html", context)
        if action == "decide":
            if not is_device_admin(request.user):
                context["facts"] = _facts(grant)
                context["error"] = "Only admins can approve a device login."
                return render(request, "community_base/device_login/device.html", context)
            approve = request.POST.get("decision") == "approve"
            grant.status = DeviceGrantStatus.APPROVED if approve else DeviceGrantStatus.DENIED
            grant.approved_by = request.user if approve else None
            grant.decided_at = timezone.now()
            grant.save(update_fields=["status", "approved_by", "decided_at"])
            context["result"] = "approved" if approve else "denied"
            return render(request, "community_base/device_login/device.html", context)
        context["facts"] = _facts(grant)
        return render(request, "community_base/device_login/device.html", context)
    code = request.GET.get("code", "")
    context["code"] = code
    if code:
        if not is_valid_user_code(code):
            context["error"] = "Enter the 8-character code shown by the CLI."
        else:
            grant = _grant_for_user_code(code)
            if grant is None or grant.is_expired or grant.status != DeviceGrantStatus.PENDING:
                context["error"] = "That code is not waiting for confirmation."
            else:
                context["facts"] = _facts(grant)
    return render(request, "community_base/device_login/device.html", context)


def _facts(grant: DeviceGrant) -> dict:
    return {
        "label": grant.label,
        "request_ip": grant.request_ip,
        "created_at": grant.created_at,
        "expires_at": grant.expires_at,
        "now": timezone.now(),
    }
