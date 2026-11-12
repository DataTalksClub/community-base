from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from community_base.jobs.runner import PermanentJobError, RetryableJobError
from community_base.kernel.hooks import configured_callable
from community_base.mail.models import EmailDelivery
from community_base.mail.relay import RelayMailClient, RelayMailError, configured_client


@dataclass(frozen=True, slots=True)
class RelayRenderedEmail:
    """Published Relay output supplied to the transitional send recorder."""

    subject: str
    html_body: str
    text_body: str

    @property
    def body_html(self) -> str:
        return self.html_body

    @property
    def html(self) -> str:
        return self.html_body

    @property
    def plain_text(self) -> str:
        return self.text_body


def deliver(delivery: EmailDelivery, context) -> None:
    client = configured_client()
    recorder = configured_callable("MAIL_SEND_RECORDER")
    try:
        rendered = (
            _preview_for_recorder(client, delivery, context) if recorder is not None else None
        )
        result = client.send(delivery, context=context)
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
        )
        delivery.state = EmailDelivery.State.PROVIDER_ACCEPTED
        delivery.reason_code = ""
        delivery.external_message_id = result.message_id
        if recorder is not None:
            recorder(delivery, rendered, result)


def _update(delivery: EmailDelivery, state: str, reason_code: str) -> None:
    EmailDelivery.objects.filter(pk=delivery.pk).update(state=state, reason_code=reason_code)


def _preview_for_recorder(
    client: RelayMailClient,
    delivery: EmailDelivery,
    context,
) -> RelayRenderedEmail:
    try:
        preview = client.preview_template(
            delivery.template_key,
            context,
            version=delivery.template_version,
        )
    except RelayMailError as error:
        if error.ambiguous:
            raise RelayMailError("relay_preview_unavailable", retryable=True) from error
        raise
    return RelayRenderedEmail(
        subject=preview["subject"],
        html_body=preview["html_body"],
        text_body=preview["text_body"],
    )
