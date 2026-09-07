"""Leaderboard complaint creation and resolution.

Ported from the DTC donor view core ``_save_leaderboard_complaint`` and the
studio ``resolve_leaderboard_complaint_response``: creation records an open
complaint (the model defaults ``resolved`` to False); resolution sets the
three resolve fields with ``update_fields``. Resolution never recomputes
scores or touches the leaderboard; correcting data goes through the scoring
services, which trigger refreshes on their own.
"""

from django.utils import timezone

from community_base.coursework.models import LeaderboardComplaint


def create_leaderboard_complaint(
    *,
    enrollment,
    reporter,
    issue_type: str,
    description: str,
) -> LeaderboardComplaint:
    return LeaderboardComplaint.objects.create(
        enrollment=enrollment,
        reporter=reporter,
        issue_type=issue_type,
        description=description,
    )


def resolve_leaderboard_complaint(
    *,
    complaint: LeaderboardComplaint,
    resolved_by,
    resolved_at=None,
) -> LeaderboardComplaint:
    complaint.resolved = True
    complaint.resolved_at = resolved_at if resolved_at is not None else timezone.now()
    complaint.resolved_by = resolved_by
    complaint.save(update_fields=["resolved", "resolved_at", "resolved_by"])
    return complaint
