from __future__ import annotations

from django.db import transaction

from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.mail.models import EmailDelivery
from community_base.mail.relay import RelayMailError, configured_client


def deliver(delivery: EmailDelivery, context) -> None:
    del context
    try:
        result = configured_client().send(delivery)
    except RelayMailError as error:
        if error.suppressed:
            _update(delivery, EmailDelivery.State.SUPPRESSED, error.reason_code)
            return
        if error.ambiguous:
            _update(delivery, EmailDelivery.State.AMBIGUOUS, error.code)
            raise PermanentJobError("mail_delivery_ambiguous") from error
        if error.retryable:
            _update(delivery, EmailDelivery.State.RETRYABLE, error.code)
            raise RetryableJobError("relay_mail_unavailable") from error
        _update(delivery, EmailDelivery.State.DEAD, error.code)
        raise PermanentJobError("relay_mail_rejected") from error
    with transaction.atomic():
        EmailDelivery.objects.filter(pk=delivery.pk).update(
            state=EmailDelivery.State.PROVIDER_ACCEPTED,
            reason_code="",
            external_message_id=result.message_id,
            template_version=result.template_version,
        )


def _update(delivery: EmailDelivery, state: str, reason_code: str) -> None:
    EmailDelivery.objects.filter(pk=delivery.pk).update(state=state, reason_code=reason_code)
