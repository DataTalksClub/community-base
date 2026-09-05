from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils.dateparse import parse_datetime

from community_base.mail.callbacks import apply_callback
from community_base.mail.models import EmailDelivery
from community_base.mail.relay import RelayMailClient, RelayMailError, configured_client

STATUS_STATES = {
    "queued": EmailDelivery.State.QUEUED,
    "retrying": EmailDelivery.State.RETRYABLE,
    "retryable": EmailDelivery.State.RETRYABLE,
    "sent": EmailDelivery.State.PROVIDER_ACCEPTED,
    "provider_accepted": EmailDelivery.State.PROVIDER_ACCEPTED,
    "delivered": EmailDelivery.State.DELIVERED,
    "ambiguous": EmailDelivery.State.AMBIGUOUS,
    "skipped": EmailDelivery.State.SUPPRESSED,
    "suppressed": EmailDelivery.State.SUPPRESSED,
    "failed": EmailDelivery.State.DEAD,
    "dead": EmailDelivery.State.DEAD,
    "bounced": EmailDelivery.State.HARD_BOUNCED,
    "hard_bounced": EmailDelivery.State.HARD_BOUNCED,
    "complained": EmailDelivery.State.COMPLAINED,
}


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    received: int
    matched: int
    changed: int
    missing: int


def reconcile_deliveries(
    since: datetime,
    *,
    client: RelayMailClient | None = None,
) -> ReconciliationResult:
    remote = (client or configured_client()).messages_since(since)
    matched = changed = missing = 0
    for message in remote:
        state = STATUS_STATES.get(message.status)
        if state is None or parse_datetime(message.updated_at) is None:
            raise RelayMailError("malformed_messages_response")
        delivery = EmailDelivery.objects.filter(idempotency_key=message.client_reference).first()
        if delivery is None:
            missing += 1
            continue
        matched += 1
        if delivery.template_key != message.template_key:
            raise RelayMailError("message_delivery_conflict")
        with transaction.atomic():
            locked = EmailDelivery.objects.select_for_update().get(pk=delivery.pk)
            if locked.external_message_id and locked.external_message_id != message.message_id:
                raise RelayMailError("message_delivery_conflict")
            EmailDelivery.objects.filter(pk=locked.pk).update(
                external_message_id=message.message_id,
                template_version=message.template_version,
            )
            digest = hashlib.sha256(
                f"{message.message_id}\0{message.status}\0{message.updated_at}".encode()
            ).hexdigest()
            result = apply_callback(
                event_id=f"reconcile:{digest}",
                event_type=f"reconciliation.{message.status}",
                delivery_id=locked.id,
                state=state,
                reason_code=message.reason_code,
            )
        changed += int(result.applied)
    return ReconciliationResult(len(remote), matched, changed, missing)
