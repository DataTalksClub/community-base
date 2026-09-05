from __future__ import annotations

import uuid

from community_base.jobs.registry import JobContext, JobPayload, register_handler
from community_base.jobs.runner import PermanentJobError
from community_base.mail.backends import get_backend
from community_base.mail.models import EmailDelivery
from community_base.mail.service import take_context


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
    backend.deliver(delivery, take_context(delivery.id))
    EmailDelivery.objects.filter(pk=delivery.id, state=EmailDelivery.State.PENDING).update(
        state=EmailDelivery.State.PROVIDER_ACCEPTED
    )
