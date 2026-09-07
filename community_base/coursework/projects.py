"""Project submission services: github and commit capture, learning-in-public links.

One learner has one real submission per project (``volunteer_review_only`` is false);
resubmitting refreshes ``submitted_at`` on the same row. Confirmation mail and delivery
syncs are site-side concerns. The learning-in-public scores are computed here so the
peer-review rollup and the submission service share one definition.
"""

import ipaddress
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils import timezone

from community_base.coursework.models import ProjectSubmission

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
    commit_id: str,
    learning_in_public_links: list[str] | None = None,
    time_spent: float | None = None,
    problems_comments: str = "",
    faq_contribution_url: str = "",
) -> tuple[ProjectSubmission, bool]:
    """Create or update the learner's submission, honouring the project field toggles."""
    submission = learner_submission_for(project, enrollment.user)
    created = submission is None
    if created:
        submission = ProjectSubmission(
            project=project, student=enrollment.user, enrollment=enrollment
        )
    else:
        submission.submitted_at = timezone.now()

    submission.github_link = github_link
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

    submission.full_clean()
    submission.save()
    return submission, created


def delete_project_submission(project, user) -> bool:
    submission = learner_submission_for(project, user)
    if submission is None:
        return False
    submission.delete()
    return True
