"""Enrollment learning-in-public preference service.

Ported from the donor ``courses/services/enrollment_flags.py``: disabling the
preference zeroes the learner's learning-in-public score components, rescores
the affected submissions without them and refreshes the leaderboard, all
inside one transaction. Enabling again only refreshes the leaderboard; future
scoring picks the components back up through ``scoring.update_score`` and the
project scoring services.
"""

from django.db import transaction

from community_base.coursework.leaderboard import update_leaderboard
from community_base.coursework.models import ProjectSubmission, Submission


@transaction.atomic
def set_learning_in_public_disabled(enrollment, *, disabled=True):
    """Store the preference and rescore the enrollment's submissions without LIP parts."""

    enrollment.disable_learning_in_public = disabled
    enrollment.save(update_fields=["disable_learning_in_public"])
    if not disabled:
        update_leaderboard(enrollment.cohort)
        return

    homework_submissions = []
    for submission in Submission.objects.filter(enrollment=enrollment):
        if submission.learning_in_public_score == 0:
            continue
        submission.learning_in_public_score = 0
        submission.total_score = submission.questions_score + submission.faq_score
        homework_submissions.append(submission)
    Submission.objects.bulk_update(
        homework_submissions,
        ["learning_in_public_score", "total_score"],
    )

    project_submissions = []
    for submission in ProjectSubmission.objects.filter(enrollment=enrollment):
        if (
            submission.project_learning_in_public_score == 0
            and submission.peer_review_learning_in_public_score == 0
        ):
            continue
        submission.project_learning_in_public_score = 0
        submission.peer_review_learning_in_public_score = 0
        submission.total_score = (
            submission.project_score + submission.project_faq_score + submission.peer_review_score
        )
        project_submissions.append(submission)
    ProjectSubmission.objects.bulk_update(
        project_submissions,
        [
            "project_learning_in_public_score",
            "peer_review_learning_in_public_score",
            "total_score",
        ],
    )

    update_leaderboard(enrollment.cohort)
