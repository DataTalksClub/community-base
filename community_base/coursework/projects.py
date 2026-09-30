"""Project submission services: github and commit capture, learning-in-public links.

One learner has one real submission per project (``volunteer_review_only`` is false);
resubmitting refreshes ``submitted_at`` on the same row. Confirmation mail and delivery
syncs are site-side concerns. The learning-in-public scores are computed here so the
peer-review rollup and the submission service share one definition.
"""

import ipaddress
from collections.abc import Callable
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from community_base.coursework.models import (
    ProjectState,
    ProjectSubmission,
    SubmissionReviewState,
)

WEB_LINK_VALIDATOR = URLValidator(schemes=["http", "https"])


def _is_private_or_local_host(host: str) -> bool:
    if not host or host.lower() == "localhost" or host.lower().endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return not address.is_global


def _validate_learning_in_public_link(link: str) -> None:
    try:
        WEB_LINK_VALIDATOR(link)
        if _is_private_or_local_host(urlsplit(link).hostname or ""):
            raise ValidationError("The link host is not public.")
    except ValidationError:
        raise ValidationError(
            "Learning in public links must be valid public HTTP or HTTPS URLs."
        ) from None


def clean_learning_in_public_links(links: list[str], cap: int) -> list[str]:
    """Strip, de-duplicate, cap and validate learner-provided links, in order."""
    cleaned_links = []
    for link in links:
        link = link.strip()
        if not link or link in cleaned_links:
            continue
        if len(cleaned_links) >= cap:
            break
        _validate_learning_in_public_link(link)
        cleaned_links.append(link)
    return cleaned_links


def project_lip_score(submission: ProjectSubmission, project) -> int:
    """Learning-in-public points for the submission's own links, capped per project."""
    if submission.enrollment.disable_learning_in_public:
        return 0
    if not submission.learning_in_public_links:
        return 0
    links_count = len(submission.learning_in_public_links)
    return min(links_count, project.learning_in_public_cap_project)


def peer_review_lip_score(submission: ProjectSubmission, project, reviewed) -> int:
    """Learning-in-public points for the reviews the submission gave, capped per review."""
    if submission.enrollment.disable_learning_in_public:
        return 0
    cap = project.learning_in_public_cap_review
    total = 0
    for review in reviewed:
        if not review.learning_in_public_links:
            continue
        links_count = len(review.learning_in_public_links)
        total += min(links_count, cap)
    return total


def project_accepts_submissions(project, now=None) -> bool:
    """Whether the project takes new submissions and edits right now.

    The project must be collecting submissions, and a dated project's ``submission_due_date``
    must not have passed. A self-paced project has no due date, so only its state closes it.
    """
    if project.state != ProjectState.COLLECTING_SUBMISSIONS.value:
        return False
    due = project.submission_due_date
    return due is None or (now or timezone.now()) <= due


def submission_editable(project, submission, now=None) -> bool:
    """Whether a learner may still save or remove ``submission`` (``None``: create one).

    Edits are allowed until the deadline and locked after it. A pooled (self-paced) submission
    also locks once it joins a review batch, because peers are then reviewing that exact link.
    """
    if not project_accepts_submissions(project, now):
        return False
    if submission is None or not project.uses_pooled_review:
        return True
    return submission.review_state == SubmissionReviewState.AWAITING_ASSIGNMENT.value


def learner_submission_for(project, user) -> ProjectSubmission | None:
    return ProjectSubmission.objects.filter(
        project=project, student=user, volunteer_review_only=False
    ).first()


@transaction.atomic
def submit_project(
    project,
    enrollment,
    *,
    github_link: str,
    commit_id: str = "",
    learning_in_public_links: list[str] | None = None,
    time_spent: float | None = None,
    problems_comments: str = "",
    faq_contribution_url: str = "",
    before_save: Callable[[ProjectSubmission], None] | None = None,
) -> tuple[ProjectSubmission, bool]:
    """Create or update the learner's submission, honouring the project field toggles.

    ``before_save`` runs on the populated submission just before ``full_clean``, inside the same
    transaction. A host form uses it to write the fields it adds itself (C5.2n), so their model
    validation and the save stay one step.
    """
    submission = learner_submission_for(project, enrollment.user)
    created = submission is None
    if created:
        submission = ProjectSubmission(
            project=project, student=enrollment.user, enrollment=enrollment
        )
    else:
        submission.submitted_at = timezone.now()

    submission.github_link = github_link
    # With the toggle off the form never shows the field, so nothing stale is kept; with it on,
    # ``ProjectSubmission.clean`` requires a value.
    submission.commit_id = ""
    if project.commit_id_field:
        submission.commit_id = commit_id

    if project.learning_in_public_cap_project > 0:
        submission.learning_in_public_links = clean_learning_in_public_links(
            learning_in_public_links or [], project.learning_in_public_cap_project
        )
    if project.time_spent_project_field and time_spent is not None:
        submission.time_spent = time_spent
    if project.problems_comments_field:
        submission.problems_comments = (problems_comments or "").strip()
    if project.faq_contribution_field:
        submission.faq_contribution_url = (faq_contribution_url or "").strip()
    if before_save is not None:
        before_save(submission)

    submission.full_clean()
    submission.save()

    if project.uses_pooled_review:
        # Local import: pooling.py imports review.py, which imports this module
        # (clean_learning_in_public_links, peer_review_lip_score, project_lip_score); importing
        # pooling at module level here would be circular. Dispatched after commit so a batch is
        # never formed from a submission that could still roll back.
        def _form_batches():
            from community_base.coursework.pooling import form_pooled_batches

            form_pooled_batches(project)

        transaction.on_commit(_form_batches)

    return submission, created


def delete_project_submission(project, user) -> bool:
    submission = learner_submission_for(project, user)
    if submission is None:
        return False
    submission.delete()
    return True
