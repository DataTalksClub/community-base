"""Studio operations for coursework, one thin wrapper per staff action.

The donor views (``studio_courses``) inline these calls; the package keeps
them as services so the studio views stay message-and-redirect shells.
``rescore_homework`` with ``force=False`` is the donor's score action and
``force=True`` the donor's rescore, where the package scoring service's
``force`` flag replaces the donor's reset-state-to-OPEN dance. Services that
are not already transactional in the package run inside one here.
"""

from dataclasses import dataclass

from django.db import transaction

from community_base.coursework.leaderboard import (
    resolve_leaderboard_complaint as _resolve_leaderboard_complaint,
)
from community_base.coursework.leaderboard import (
    update_leaderboard as _update_leaderboard,
)
from community_base.coursework.review import (
    ProjectActionStatus,
)
from community_base.coursework.review import (
    assign_peer_reviews_for_project as _assign_peer_reviews_for_project,
)
from community_base.coursework.review import (
    score_project as _score_project_service,
)
from community_base.coursework.scoring import (
    HomeworkScoringStatus,
    score_homework_submissions,
)


@dataclass(frozen=True)
class StudioActionResult:
    """Outcome of one studio action, ready to become a view message."""

    ok: bool
    message: str


def rescore_homework(homework, *, force: bool = True) -> StudioActionResult:
    """Score one homework's submissions; ``force=True`` is the donor rescore.

    A rescore of a homework that was never scored stays a warning, as in the
    donor's ``homework_rescore`` view.
    """

    if force and not homework.is_scored():
        return StudioActionResult(
            ok=False,
            message=f"{homework.title} is not scored yet. Use Score submissions instead.",
        )
    status, message = score_homework_submissions(homework.id, force=force)
    return StudioActionResult(
        ok=status is HomeworkScoringStatus.OK,
        message=message,
    )


def assign_project_reviews(project) -> StudioActionResult:
    """Assign the peer-review graph and open the project's review window."""

    status, message = _assign_peer_reviews_for_project(project)
    return StudioActionResult(
        ok=status is ProjectActionStatus.OK,
        message=message,
    )


def score_project(project) -> StudioActionResult:
    """Score every submission reachable from the project's reviews."""

    status, message = _score_project_service(project)
    return StudioActionResult(
        ok=status is ProjectActionStatus.OK,
        message=message,
    )


@transaction.atomic
def recompute_leaderboard(cohort) -> StudioActionResult:
    """Recompute enrollment totals and leaderboard positions for one cohort."""

    _update_leaderboard(cohort)
    return StudioActionResult(
        ok=True,
        message=f"Leaderboard updated for cohort {cohort.pk}.",
    )


@transaction.atomic
def resolve_leaderboard_complaint(complaint, resolver) -> StudioActionResult:
    """Mark a complaint resolved; donor parity: no score recompute happens."""

    _resolve_leaderboard_complaint(complaint, resolver)
    return StudioActionResult(ok=True, message="Flag marked as resolved.")
