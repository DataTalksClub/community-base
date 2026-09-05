from __future__ import annotations

from django.utils import timezone

from community_base.jobs.backends import get_backend
from community_base.jobs.models import JobIntent


def run_due(*, limit: int = 100) -> tuple[int, int]:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError("due-job limit must be between 1 and 1000")
    intent_ids = list(
        JobIntent.objects.filter(
            status__in=JobIntent.CLAIMABLE_STATUSES,
            available_at__lte=timezone.now(),
            lease_token__isnull=True,
        )
        .order_by("available_at", "created_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    backend = get_backend()
    submitted = 0
    for intent_id in intent_ids:
        backend.submit(intent_id)
        submitted += 1
    return len(intent_ids), submitted
