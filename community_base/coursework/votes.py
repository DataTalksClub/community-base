"""Project vote recording with the per-voter, per-project cap.

The database uniqueness constraint on (submission, voter) stays the last line of
defense; this service layers the donor cap semantics on top of it: a voter holds at
most PROJECT_VOTES_PER_PROJECT votes across one project's submissions.
"""

from django.db.models import Count

from community_base.coursework.models import ProjectVote

PROJECT_VOTES_PER_PROJECT = 3


def update_project_vote(user, submission, action="vote") -> bool:
    """Record or remove one vote; returns whether the voter's vote set changed."""
    if action == "remove":
        deleted_count, _ = ProjectVote.objects.filter(
            voter=user,
            submission=submission,
        ).delete()
        return deleted_count > 0

    if ProjectVote.objects.filter(
        voter=user,
        submission=submission,
    ).exists():
        return False

    vote_count = ProjectVote.objects.filter(
        voter=user,
        submission__project=submission.project,
    ).count()
    if vote_count >= PROJECT_VOTES_PER_PROJECT:
        return False

    ProjectVote.objects.get_or_create(
        voter=user,
        submission=submission,
    )
    return True


def get_voted_submission_ids(user, cohort) -> set[int]:
    if not user.is_authenticated:
        return set()

    votes = ProjectVote.objects.filter(
        voter=user,
        submission__project__cohort=cohort,
    )
    return set(votes.values_list("submission_id", flat=True))


def get_project_vote_counts(user, cohort) -> dict[int, int]:
    if not user.is_authenticated:
        return {}

    project_vote_counts = {}
    rows = (
        ProjectVote.objects.filter(
            voter=user,
            submission__project__cohort=cohort,
        )
        .values("submission__project_id")
        .annotate(count=Count("id"))
    )
    for row in rows:
        project_vote_counts[row["submission__project_id"]] = row["count"]
    return project_vote_counts
