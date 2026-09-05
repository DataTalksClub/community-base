from __future__ import annotations

import hmac
import json

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from community_base.jobs.ingress import SIGNATURE_TOLERANCE_SECONDS, sign_body
from community_base.kernel.conf import get
from community_base.kernel.context import is_safe_external_context_id
from community_base.mail.callbacks import (
    CallbackConflict,
    CallbackError,
    apply_callback,
    record_callback_event,
)
from community_base.mail.models import EmailDelivery

MAX_CALLBACK_BODY_BYTES = 32_768
EVENT_STATES = {
    "delivery.accepted": EmailDelivery.State.PROVIDER_ACCEPTED,
    "delivery.delivered": EmailDelivery.State.DELIVERED,
    "delivery.complained": EmailDelivery.State.COMPLAINED,
    "delivery.suppressed": EmailDelivery.State.SUPPRESSED,
}
NON_TRANSITION_EVENTS = frozenset(
    {"engagement.opened", "engagement.clicked", "subscription.changed"}
)


@csrf_exempt
def receive_callback(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _error("method_not_allowed", 405)
    body = request.body
    if len(body) > MAX_CALLBACK_BODY_BYTES:
        return _error("body_too_large", 400)
    auth_error = _verify_signature(request, body)
    if auth_error is not None:
        return auth_error
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("invalid_payload", 400)
    if not isinstance(document, dict):
        return _error("invalid_payload", 400)
    try:
        result = _apply(document)
    except CallbackConflict:
        return _error("event_conflict", 409)
    except CallbackError:
        return _error("invalid_payload", 400)
    if result is None:
        return _error("delivery_not_found", 404)
    return JsonResponse({"status": "ok", "created": result.created, "applied": result.applied})


def _apply(document: dict):
    event_id = document.get("event_id")
    event_type = document.get("event_type")
    client_reference = document.get("client_reference")
    message_id = document.get("message_id")
    reason_code = document.get("reason_code", "")
    occurred_at = document.get("timestamp")
    if isinstance(message_id, int) and not isinstance(message_id, bool):
        message_id = str(message_id)
    if (
        not isinstance(event_id, str)
        or not isinstance(event_type, str)
        or not isinstance(reason_code, str)
        or (message_id is not None and not is_safe_external_context_id(message_id))
        or not isinstance(occurred_at, str)
        or parse_datetime(occurred_at) is None
    ):
        raise CallbackError("invalid callback payload")
    delivery = None
    if isinstance(client_reference, str):
        delivery = EmailDelivery.objects.filter(idempotency_key=client_reference).first()
    if event_type != "subscription.changed" and delivery is None:
        return None
    if delivery is not None and message_id:
        if delivery.external_message_id and delivery.external_message_id != message_id:
            raise CallbackConflict("callback message id conflicts with delivery")
        if not delivery.external_message_id:
            EmailDelivery.objects.filter(pk=delivery.pk, external_message_id="").update(
                external_message_id=message_id
            )
    state = EVENT_STATES.get(event_type)
    if event_type == "delivery.bounced":
        state = (
            EmailDelivery.State.HARD_BOUNCED
            if document.get("bounce_type") == "hard"
            else EmailDelivery.State.RETRYABLE
        )
    if state is not None:
        return apply_callback(
            event_id=event_id,
            event_type=event_type,
            delivery_id=delivery.id,
            state=state,
            reason_code=reason_code,
        )
    if event_type not in NON_TRANSITION_EVENTS:
        raise CallbackError("unknown callback event type")
    return record_callback_event(
        event_id=event_id,
        event_type=event_type,
        delivery=delivery,
        reason_code=reason_code,
    )


def _verify_signature(request: HttpRequest, body: bytes) -> JsonResponse | None:
    secret = get("RELAY_WEBHOOK_SECRET")
    if not isinstance(secret, str) or not secret:
        return _error("ingress_not_configured", 503)
    timestamp = request.headers.get("X-Relay-Timestamp", "")
    supplied = request.headers.get("X-Relay-Signature", "")
    try:
        age = abs(int(timezone.now().timestamp()) - int(timestamp))
    except ValueError:
        return _error("invalid_signature", 401)
    if age > SIGNATURE_TOLERANCE_SECONDS:
        return _error("stale_signature", 401)
    if not hmac.compare_digest(supplied, sign_body(body, timestamp, secret)):
        return _error("invalid_signature", 401)
    return None


def _error(code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": code}, status=status)
