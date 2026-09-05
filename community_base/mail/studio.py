from __future__ import annotations

from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache

from community_base.kernel.decorators import staff_required
from community_base.mail.models import EmailDelivery


def redacted_hash(value: str) -> str:
    return f"sha256:{value[:12]}"


def masked_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    return f"{local[:1]}***@{domain}" if separator else "[REDACTED]"


@never_cache
@staff_required
def deliveries_list(request):
    deliveries = EmailDelivery.objects.all()
    state = request.GET.get("state", "")
    purpose = request.GET.get("purpose", "")
    if state in EmailDelivery.State.values:
        deliveries = deliveries.filter(state=state)
    if purpose:
        deliveries = deliveries.filter(purpose=purpose)
    rows = [(delivery, masked_email(delivery.recipient_email)) for delivery in deliveries[:200]]
    return render(
        request,
        "community_base/mail/deliveries.html",
        {
            "rows": rows,
            "states": EmailDelivery.State.choices,
            "selected_state": state,
            "selected_purpose": purpose,
        },
    )


@never_cache
@staff_required
def delivery_detail(request, delivery_id):
    delivery = get_object_or_404(
        EmailDelivery.objects.prefetch_related("callback_events"),
        pk=delivery_id,
    )
    return render(
        request,
        "community_base/mail/delivery_detail.html",
        {
            "delivery": delivery,
            "recipient": masked_email(delivery.recipient_email),
            "context_hash": redacted_hash(delivery.context_hash),
        },
    )
