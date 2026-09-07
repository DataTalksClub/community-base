"""Site wiring points for coursework side effects.

The donor services record analytics events and refresh leaderboards inline.
The package exposes those points as kernel hooks with discard defaults; sites
wire their own analytics and leaderboard implementations through
``COMMUNITY_BASE``.
"""

from community_base.kernel.hooks import Hook


def discard_event(**event) -> None:
    """Default observer for sites that have not configured a sink."""


class CourseworkHooks:
    peer_reviews_assigned = Hook("COURSEWORK_PEER_REVIEWS_ASSIGNED", discard_event)
    peer_reviews_assignment_failed = Hook(
        "COURSEWORK_PEER_REVIEWS_ASSIGNMENT_FAILED", discard_event
    )
    optional_review_added = Hook("COURSEWORK_OPTIONAL_REVIEW_ADDED", discard_event)
    optional_review_deleted = Hook("COURSEWORK_OPTIONAL_REVIEW_DELETED", discard_event)
    project_scored = Hook("COURSEWORK_PROJECT_SCORED", discard_event)
    project_scoring_failed = Hook("COURSEWORK_PROJECT_SCORING_FAILED", discard_event)
    project_leaderboard_updater = Hook("COURSEWORK_PROJECT_LEADERBOARD_UPDATER", discard_event)


hooks = CourseworkHooks()
