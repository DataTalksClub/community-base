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
    using: str = DEFAULT_DB_ALIAS,
) -> CallbackResult:
    with transaction.atomic(using=using):
        return _apply_callback(
            event_id=event_id,
            delivery_id=delivery_id,
            state=state,
            reason_code=reason_code,
            using=using,
        )


def _apply_callback(
    *,
    event_id: str,
    delivery_id: uuid.UUID | str,
    state: str,
    reason_code: str,
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
    if reason_code and (
        not isinstance(reason_code, str) or not REASON_PATTERN.fullmatch(reason_code)
    ):
        raise CallbackError("invalid callback reason code")

    existing = CallbackEvent.objects.using(using).filter(event_id=event_id).first()
    if existing is not None:
        supplied = (parsed_delivery_id, state, reason_code)
        recorded = (existing.delivery_id, existing.state, existing.reason_code)
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
        state=state,
        reason_code=reason_code,
    )
    applied = STATE_PRECEDENCE[state] > STATE_PRECEDENCE[delivery.state]
    if applied:
        delivery.state = state
        delivery.reason_code = reason_code
        delivery.save(update_fields=("state", "reason_code", "updated_at"), using=using)
    return CallbackResult(event=event, created=True, applied=applied)
