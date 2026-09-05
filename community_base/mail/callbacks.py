from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from django.db import DEFAULT_DB_ALIAS, transaction

from community_base.mail.models import CallbackEvent, EmailDelivery

EVENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")

# Callback order is not delivery order. A deterministic precedence makes every
# permutation converge while keeping adverse provider outcomes authoritative.
STATE_PRECEDENCE = {
    EmailDelivery.State.PENDING: 0,
    EmailDelivery.State.QUEUED: 10,
    EmailDelivery.State.RETRYABLE: 15,
    EmailDelivery.State.LEASED: 20,
    EmailDelivery.State.PROVIDER_ACCEPTED: 30,
    EmailDelivery.State.AMBIGUOUS: 35,
    EmailDelivery.State.DELIVERED: 40,
    EmailDelivery.State.DEAD: 50,
    EmailDelivery.State.SUPPRESSED: 60,
    EmailDelivery.State.HARD_BOUNCED: 70,
    EmailDelivery.State.COMPLAINED: 80,
}


class CallbackError(RuntimeError):
    pass


class CallbackConflict(CallbackError):
    pass


@dataclass(frozen=True, slots=True)
class CallbackResult:
    event: CallbackEvent
    created: bool
    applied: bool


def apply_callback(
    *,
    event_id: str,
    delivery_id: uuid.UUID | str,
    state: str,
    reason_code: str = "",
    event_type: str = "delivery.updated",
    using: str = DEFAULT_DB_ALIAS,
) -> CallbackResult:
    with transaction.atomic(using=using):
        return _apply_callback(
            event_id=event_id,
            delivery_id=delivery_id,
            state=state,
            reason_code=reason_code,
            event_type=event_type,
            using=using,
        )


def _apply_callback(
    *,
    event_id: str,
    delivery_id: uuid.UUID | str,
    state: str,
    reason_code: str,
    event_type: str,
    using: str,
) -> CallbackResult:
    if not isinstance(event_id, str) or not EVENT_PATTERN.fullmatch(event_id):
        raise CallbackError("invalid callback event id")
    try:
        parsed_delivery_id = uuid.UUID(str(delivery_id))
    except (TypeError, ValueError) as error:
        raise CallbackError("invalid callback delivery id") from error
    if state not in STATE_PRECEDENCE:
        raise CallbackError("invalid callback state")
    if not isinstance(event_type, str) or not EVENT_PATTERN.fullmatch(event_type):
        raise CallbackError("invalid callback event type")
    if reason_code and (
        not isinstance(reason_code, str) or not REASON_PATTERN.fullmatch(reason_code)
    ):
        raise CallbackError("invalid callback reason code")

    existing = CallbackEvent.objects.using(using).filter(event_id=event_id).first()
    if existing is not None:
        supplied = (parsed_delivery_id, event_type, state, reason_code)
        recorded = (
            existing.delivery_id,
            existing.event_type,
            existing.state,
            existing.reason_code,
        )
        if supplied != recorded:
            raise CallbackConflict("callback event id conflicts with recorded event")
        return CallbackResult(event=existing, created=False, applied=False)

    try:
        delivery = EmailDelivery.objects.using(using).select_for_update().get(pk=parsed_delivery_id)
    except EmailDelivery.DoesNotExist as error:
        raise CallbackError("callback delivery does not exist") from error
    event = CallbackEvent.objects.using(using).create(
        event_id=event_id,
        delivery=delivery,
        event_type=event_type,
        state=state,
        reason_code=reason_code,
    )
    applied = STATE_PRECEDENCE[state] > STATE_PRECEDENCE[delivery.state]
    if applied:
        delivery.state = state
        delivery.reason_code = reason_code
        delivery.save(update_fields=("state", "reason_code", "updated_at"), using=using)
    return CallbackResult(event=event, created=True, applied=applied)


def record_callback_event(
    *,
    event_id: str,
    event_type: str,
    delivery: EmailDelivery | None,
    reason_code: str = "",
    using: str = DEFAULT_DB_ALIAS,
) -> CallbackResult:
    """Deduplicate a callback that carries no delivery-state transition."""

    if not isinstance(event_id, str) or not EVENT_PATTERN.fullmatch(event_id):
        raise CallbackError("invalid callback event id")
    if not isinstance(event_type, str) or not EVENT_PATTERN.fullmatch(event_type):
        raise CallbackError("invalid callback event type")
    if reason_code and not REASON_PATTERN.fullmatch(reason_code):
        raise CallbackError("invalid callback reason code")
    with transaction.atomic(using=using):
        existing = CallbackEvent.objects.using(using).filter(event_id=event_id).first()
        delivery_id = delivery.pk if delivery is not None else None
        if existing is not None:
            if (
                existing.delivery_id,
                existing.event_type,
                existing.state,
                existing.reason_code,
            ) != (delivery_id, event_type, "", reason_code):
                raise CallbackConflict("callback event id conflicts with recorded event")
            return CallbackResult(existing, created=False, applied=False)
        event = CallbackEvent.objects.using(using).create(
            event_id=event_id,
            event_type=event_type,
            delivery=delivery,
            reason_code=reason_code,
        )
        return CallbackResult(event, created=True, applied=False)
