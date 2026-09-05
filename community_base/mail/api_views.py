from __future__ import annotations

import uuid

from django.db import transaction

from community_base.api import route
from community_base.api.errors import APIError
from community_base.api.registry import json_response
from community_base.api.safety import parse_pagination
from community_base.mail.models import EmailDelivery
from community_base.mail.service import resend

DELIVERY_SCHEMA = {
    "type": "object",
    "required": ["id", "purpose", "state", "recipient", "created_at"],
}
DELIVERIES_SCHEMA = {
    "type": "object",
    "properties": {"deliveries": {"type": "array"}},
}


def _not_found() -> APIError:
    return APIError(404, "mail_delivery_not_found", "Mail delivery was not found.")


def _delivery(delivery_id) -> EmailDelivery:
    try:
        parsed = uuid.UUID(str(delivery_id))
    except (TypeError, ValueError) as error:
        raise _not_found() from error
    try:
        return EmailDelivery.objects.select_related("recipient_user").get(pk=parsed)
    except EmailDelivery.DoesNotExist as error:
        raise _not_found() from error


def _masked_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if not separator:
        return "[REDACTED]"
    visible = local[:1]
    return f"{visible}***@{domain}"


def serialize(delivery: EmailDelivery, *, detail: bool = False) -> dict:
    payload = {
        "id": str(delivery.id),
        "purpose": delivery.purpose,
        "category": delivery.category or None,
        "template_key": delivery.template_key,
        "template_version": delivery.template_version,
        "recipient": _masked_email(delivery.recipient_email),
        "state": delivery.state,
        "reason_code": delivery.reason_code or None,
        "sender_id": delivery.sender_id or None,
        "created_at": delivery.created_at.isoformat(),
        "updated_at": delivery.updated_at.isoformat(),
    }
    if detail:
        payload.update(
            {
                "context_hash": f"sha256:{delivery.context_hash[:12]}",
                "external_message_id": delivery.external_message_id or None,
                "job_id": str(delivery.job_id) if delivery.job_id else None,
                "related": {
                    "type": delivery.related_object_type,
                    "id": delivery.related_object_id,
                }
                if delivery.related_object_type
                else None,
                "callbacks": [
                    {
                        "event_id": event.event_id,
                        "state": event.state,
                        "reason_code": event.reason_code or None,
                        "received_at": event.received_at.isoformat(),
                    }
                    for event in delivery.callback_events.all()
                ],
            }
        )
    return payload


@route("GET", "mail/deliveries", "mail.read", "List mail deliveries", DELIVERIES_SCHEMA)
def list_deliveries(request):
    page = parse_pagination(request)
    queryset = EmailDelivery.objects.all()
    state = request.GET.get("state", "")
    purpose = request.GET.get("purpose", "")
    if state:
        if state not in EmailDelivery.State.values:
            raise APIError(400, "invalid_mail_state", "Mail delivery state is invalid.")
        queryset = queryset.filter(state=state)
    if purpose:
        queryset = queryset.filter(purpose=purpose)
    total = queryset.count()
    selected = queryset[page.offset : page.offset + page.limit]
    return json_response(
        {
            "deliveries": [serialize(item) for item in selected],
            "pagination": {"limit": page.limit, "offset": page.offset, "total": total},
        }
    )


@route(
    "GET",
    "mail/deliveries/<uuid:delivery_id>",
    "mail.read",
    "Read a mail delivery",
    DELIVERY_SCHEMA,
)
def get_delivery(request, delivery_id):
    del request
    return json_response(serialize(_delivery(delivery_id), detail=True))


@route(
    "POST",
    "mail/deliveries/<uuid:delivery_id>/resend",
    "mail.write",
    "Resend as a new mail delivery",
    DELIVERY_SCHEMA,
)
def resend_delivery(request, delivery_id):
    del request
    original = _delivery(delivery_id)
    with transaction.atomic():
        replacement = resend(original)
    return json_response(serialize(replacement, detail=True), status=201)
