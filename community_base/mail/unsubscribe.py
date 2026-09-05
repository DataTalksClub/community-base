from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import DEFAULT_DB_ALIAS, transaction

from community_base.jobs.dispatch import dispatch_after_commit
from community_base.mail import relay_links
from community_base.mail.models import PendingUnsubscribe

UNSUBSCRIBE_REPLAY_HANDLER = "cb_mail.unsubscribe_replay"
UNSUBSCRIBE_REPLAY_MAX_ATTEMPTS = 20


@dataclass(frozen=True, slots=True)
class AcceptedUnsubscribe:
    pending_id: uuid.UUID
    created: bool


def accept_unsubscribe_for_replay(
    *, token: str, scope: str, using: str = DEFAULT_DB_ALIAS
) -> AcceptedUnsubscribe:
    if not relay_links.is_well_formed_token(token):
        raise ValueError("malformed unsubscribe token")
    if scope not in relay_links.UNSUBSCRIBE_SCOPES:
        raise ValueError("unsupported unsubscribe scope")
    with transaction.atomic(using=using):
        PendingUnsubscribe.objects.using(using).filter(unsubscribe_token=token).exclude(
            status=PendingUnsubscribe.Status.PENDING
        ).delete()
        pending, created = PendingUnsubscribe.objects.using(using).get_or_create(
            unsubscribe_token=token,
            defaults={
                "token_fingerprint": relay_links.token_fingerprint(token),
                "scope": scope,
                "status": PendingUnsubscribe.Status.PENDING,
            },
        )
        if not created and pending.scope != scope:
            pending.scope = scope
            pending.save(using=using, update_fields=("scope", "updated_at"))
        dispatch_after_commit(
            UNSUBSCRIBE_REPLAY_HANDLER,
            key=f"mail:unsubscribe-replay:{pending.id}",
            payload={"pending_unsubscribe_id": str(pending.id)},
            max_attempts=UNSUBSCRIBE_REPLAY_MAX_ATTEMPTS,
            using=using,
        )
    return AcceptedUnsubscribe(pending_id=pending.id, created=created)


def replay_pending_unsubscribe(pending_id: uuid.UUID, *, using: str = DEFAULT_DB_ALIAS) -> str:
    pending = PendingUnsubscribe.objects.using(using).filter(pk=pending_id).first()
    if pending is None:
        return "absent"
    if pending.status != PendingUnsubscribe.Status.PENDING:
        return "settled"
    result = relay_links.submit_unsubscribe(pending.unsubscribe_token, pending.scope)
    PendingUnsubscribe.objects.using(using).filter(pk=pending.pk).update(
        attempt_count=pending.attempt_count + 1,
        last_outcome=result.outcome.value,
    )
    if result.outcome is relay_links.BridgeOutcome.RECORDED:
        PendingUnsubscribe.objects.using(using).filter(pk=pending.pk).delete()
        return "applied"
    if result.outcome is relay_links.BridgeOutcome.REJECTED:
        PendingUnsubscribe.objects.using(using).filter(pk=pending.pk).update(
            status=PendingUnsubscribe.Status.REJECTED
        )
        return "rejected"
    return result.outcome.value
