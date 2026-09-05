from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from django.db import DEFAULT_DB_ALIAS, connections

from community_base.jobs.dispatch import DispatchConflict, dispatch_after_commit
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve
from community_base.mail.models import EmailDelivery

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class MailError(RuntimeError):
    pass


class MailConflict(MailError):
    pass


def send(
    purpose: str,
    to: str,
    context: Mapping[str, Any],
    idempotency_key: str,
    category: str | None = None,
    user=None,
    related=None,
    sender: str | None = None,
    extra: Mapping[str, Any] | None = None,
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> EmailDelivery:
    if not connections[using].in_atomic_block:
        raise MailError("durable mail requires an active transaction")
    _validate_identifier("purpose", purpose, 128)
    if not isinstance(to, str) or not to or len(to) > 254 or "@" not in to:
        raise MailError("invalid recipient")
    if not isinstance(context, Mapping):
        raise MailError("mail context must be an object")
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise MailError("invalid mail idempotency key")
    category_value = category or ""
    sender_value = sender or ""
    transport_options = _transport_options(extra)
    context_hash = _context_hash(context)
    related_type, related_id = _related_reference(related)
    immutable = {
        "purpose": purpose,
        "category": category_value,
        "template_key": purpose,
        "template_version": 1,
        "recipient_email": to,
        "recipient_user_id": getattr(user, "pk", None),
        "context_hash": context_hash,
        "transport_options": transport_options,
        "sender_id": sender_value,
        "related_object_type": related_type,
        "related_object_id": related_id,
    }
    existing = EmailDelivery.objects.using(using).filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if any(getattr(existing, field) != value for field, value in immutable.items()):
            raise MailConflict("idempotency key conflicts with an existing mail delivery")
        return existing

    resolver = get("MAIL_PREFERENCE_RESOLVER")
    resolver = resolve(resolver) if isinstance(resolver, str) else resolver
    decision = resolver(
        purpose=purpose,
        category=category_value or None,
        to=to,
        user=user,
    )
    allowed, reason = _preference_decision(decision)
    delivery_id = uuid.uuid4()
    job = None
    if allowed:
        try:
            job, _ = dispatch_after_commit(
                "cb_mail.deliver",
                f"mail:{idempotency_key}",
                {"delivery_id": str(delivery_id)},
                using=using,
            )
        except DispatchConflict as error:
            raise MailConflict("mail job conflicts with an existing delivery") from error
    delivery = EmailDelivery.objects.using(using).create(
        id=delivery_id,
        idempotency_key=idempotency_key,
        state=EmailDelivery.State.PENDING if allowed else EmailDelivery.State.SUPPRESSED,
        reason_code="" if allowed else reason,
        context_data=dict(context),
        job=job,
        **immutable,
    )
    return delivery


def resend(
    original: EmailDelivery,
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> EmailDelivery:
    """Create a new audited logical delivery related to an earlier one."""

    return send(
        purpose=original.purpose,
        to=original.recipient_email,
        context=original.context_data,
        idempotency_key=f"resend:{original.id}:{uuid.uuid4()}",
        category=original.category or None,
        user=original.recipient_user,
        related=original,
        sender=original.sender_id or None,
        extra=original.transport_options,
        using=using,
    )


def _validate_identifier(name: str, value: object, limit: int) -> None:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise MailError(f"invalid {name}")


def _context_hash(context: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise MailError("mail context must contain JSON values") from error
    return hashlib.sha256(encoded.encode()).hexdigest()


def _transport_options(extra: Mapping[str, Any] | None) -> dict[str, list[str]]:
    if extra is None:
        return {}
    if not isinstance(extra, Mapping):
        raise MailError("mail extra must be an object")
    unknown = set(extra) - {"cc", "bcc"}
    if unknown:
        raise MailError("unsupported mail extra option")
    result = {}
    for name in ("cc", "bcc"):
        raw = extra.get(name)
        values = [raw] if isinstance(raw, str) else raw
        if values is None:
            continue
        if not isinstance(values, (list, tuple)):
            raise MailError(f"mail {name} must be an email or list of emails")
        normalized = []
        for value in values:
            if not isinstance(value, str) or not value.strip() or "@" not in value:
                raise MailError(f"invalid mail {name} recipient")
            normalized.append(value.strip())
        if normalized:
            result[name] = normalized
    return result


def _related_reference(related) -> tuple[str, str]:
    if related is None:
        return "", ""
    meta = getattr(related, "_meta", None)
    pk = getattr(related, "pk", None)
    if meta is None or pk is None:
        raise MailError("related must be a saved Django model")
    return meta.label_lower, str(pk)


def _preference_decision(decision) -> tuple[bool, str]:
    if decision is True or decision is None:
        return True, ""
    if decision is False:
        return False, "preference_suppressed"
    if isinstance(decision, str) and re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", decision):
        return False, decision
    raise MailError("mail preference resolver returned an invalid decision")
