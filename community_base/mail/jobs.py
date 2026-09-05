from __future__ import annotations

import uuid

from community_base.jobs.registry import JobContext, JobPayload, register_handler
from community_base.jobs.runner import PermanentJobError
from community_base.mail.backends import get_backend
from community_base.mail.models import EmailDelivery
from community_base.mail.unsubscribe import (
    UNSUBSCRIBE_REPLAY_HANDLER,
    replay_pending_unsubscribe,
)


@register_handler("cb_mail.deliver")
def deliver(context: JobContext, payload: JobPayload) -> None:
    del context
    raw_id = payload.get("delivery_id")
    if not isinstance(raw_id, str):
        raise PermanentJobError("invalid_mail_delivery_payload")
    try:
        delivery_id = uuid.UUID(raw_id)
    except ValueError as error:
        raise PermanentJobError("invalid_mail_delivery_payload") from error
    try:
        delivery = EmailDelivery.objects.get(pk=delivery_id)
    except EmailDelivery.DoesNotExist as error:
        raise PermanentJobError("mail_delivery_not_found") from error
    backend = get_backend()
    backend.deliver(delivery, delivery.context_data)
    EmailDelivery.objects.filter(pk=delivery.id, state=EmailDelivery.State.PENDING).update(
        state=EmailDelivery.State.PROVIDER_ACCEPTED
    )


@register_handler(UNSUBSCRIBE_REPLAY_HANDLER)
def replay_unsubscribe(context: JobContext, payload: JobPayload) -> None:
    del context
    raw_id = payload.get("pending_unsubscribe_id")
    if not isinstance(raw_id, str):
        raise PermanentJobError("invalid_unsubscribe_replay_payload")
    try:
        pending_id = uuid.UUID(raw_id)
    except ValueError as error:
        raise PermanentJobError("invalid_unsubscribe_replay_payload") from error
    outcome = replay_pending_unsubscribe(pending_id)
    if outcome in {"applied", "absent", "settled", "rejected"}:
        return
    if outcome == "not_configured":
        raise PermanentJobError("relay_bridge_not_configured")
    from community_base.jobs.runner import RetryableJobError

    raise RetryableJobError("relay_unavailable")
