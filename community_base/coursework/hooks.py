"""Site wiring points for coursework side effects.

The donor services record analytics events and refresh leaderboards inline.
The package exposes those points as kernel hooks with discard defaults; sites
wire their own analytics and leaderboard implementations through
``COMMUNITY_BASE``.
"""

from community_base.kernel.hooks import Hook


def discard_event(**event) -> None:
    """Default observer for sites that have not configured a sink."""


def _default_project_leaderboard_updater(project, **kwargs):
    """Recompute the cohort leaderboard unless the site overrides the hook."""

    from community_base.coursework.leaderboard import update_leaderboard

    update_leaderboard(project.cohort)


def default_display_name_generator(enrollment, **kwargs):
    """Fallback leaderboard name; sites override it with their own word lists."""

    from django.utils.crypto import get_random_string

    return f"Learner {get_random_string(8)}"


class CourseworkHooks:
    peer_reviews_assigned = Hook("COURSEWORK_PEER_REVIEWS_ASSIGNED", discard_event)
    peer_reviews_assignment_failed = Hook(
        "COURSEWORK_PEER_REVIEWS_ASSIGNMENT_FAILED", discard_event
    )
    optional_review_added = Hook("COURSEWORK_OPTIONAL_REVIEW_ADDED", discard_event)
    optional_review_deleted = Hook("COURSEWORK_OPTIONAL_REVIEW_DELETED", discard_event)
    project_scored = Hook("COURSEWORK_PROJECT_SCORED", discard_event)
    project_scoring_failed = Hook("COURSEWORK_PROJECT_SCORING_FAILED", discard_event)
    project_leaderboard_updater = Hook(
        "COURSEWORK_PROJECT_LEADERBOARD_UPDATER", _default_project_leaderboard_updater
    )
    project_submitted = Hook("COURSEWORK_PROJECT_SUBMITTED", discard_event)
    project_deleted = Hook("COURSEWORK_PROJECT_DELETED", discard_event)
    project_vote_updated = Hook("COURSEWORK_PROJECT_VOTE_UPDATED", discard_event)
    review_submitted = Hook("COURSEWORK_REVIEW_SUBMITTED", discard_event)
    homework_submitted = Hook("COURSEWORK_HOMEWORK_SUBMITTED", discard_event)
    homework_submission_rejected = Hook("COURSEWORK_HOMEWORK_SUBMISSION_REJECTED", discard_event)
    enrollment_preferences_updated = Hook(
        "COURSEWORK_ENROLLMENT_PREFERENCES_UPDATED", discard_event
    )
    registration_submitted = Hook("COURSEWORK_REGISTRATION_SUBMITTED", discard_event)
    registration_campaign_changed = Hook("COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED", discard_event)
    certificate_issued = Hook("COURSEWORK_CERTIFICATE_ISSUED", discard_event)
    display_name_generator = Hook(
        "COURSEWORK_DISPLAY_NAME_GENERATOR", default_display_name_generator
    )


hooks = CourseworkHooks()
