from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MemoryMessage:
    delivery_id: UUID
    purpose: str
    recipient_email: str
    context: Mapping[str, Any]
    sender_id: str


outbox: list[MemoryMessage] = []


def deliver(delivery, context: Mapping[str, Any]) -> None:
    outbox.append(
        MemoryMessage(
            delivery_id=delivery.id,
            purpose=delivery.purpose,
            recipient_email=delivery.recipient_email,
            context=MappingProxyType(dict(context)),
            sender_id=delivery.sender_id,
        )
    )
