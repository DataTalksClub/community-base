"""Peer review assignment, criteria responses, evaluation rollup and project scoring.

Required reviews are drawn deterministically from the real submissions; volunteer
reviews are optional rows anchored on a placeholder ``volunteer_review_only``
submission. Scoring ends by moving the project to COMPLETED. Analytics and the
leaderboard rollup fire through ``coursework.hooks`` and default to discard;
sites wire real observers through ``COMMUNITY_BASE``.
"""

import logging
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from community_base.coursework.hooks import hooks
from community_base.coursework.models import (
    CriteriaResponse,
    PeerReview,
    PeerReviewState,
    ProjectEvaluationScore,
    ProjectState,
    ProjectSubmission,
    ReviewCriteria,
)
from community_base.coursework.projects import (
    clean_learning_in_public_links,
    peer_review_lip_score,
    project_lip_score,
)
from community_base.curriculum.models import Enrollment

logger = logging.getLogger(__name__)

# How long the peer-review window stays open after submissions close.
PEER_REVIEW_WINDOW = timedelta(days=7)
ASSIGNMENT_SEED = 42
PROJECT_NOT_COLLECTING_SUBMISSIONS_MESSAGE = (
    "Project is not in 'COLLECTING_SUBMISSIONS' state to assign peer reviews."
)
FUTURE_SUBMISSION_DUE_DATE_MESSAGE = (
    "The submission due date is in the future. Update the due date to assign peer reviews."
)
VOLUNTEER_GITHUB_LINK = "https://github.com/DataTalksClub/course-management-platform"
VOLUNTEER_COMMIT_ID = "volunteer"


class ProjectActionStatus(Enum):
    OK = "OK"
    FAIL = "Warning"


class ProjectCriteriaValidationError(ValidationError):
    """A safe, atomic rejection of criteria outside the current project rubric."""


def ceil_to_next_hour(value):
    """Round a datetime up to the start of the next whole hour.

    A value already exactly on the hour is returned unchanged
    (15:00:00 -> 15:00:00); anything with sub-hour components is rounded up
    (15:23:41 -> 16:00:00).
    """
    if value.minute == 0 and value.second == 0 and value.microsecond == 0:
        return value
    return (value + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def _assignment_precondition_failure(
    project,
    submissions_count: int,
    num_evaluations: int,
) -> tuple[ProjectActionStatus, str] | None:
    if project.state != ProjectState.COLLECTING_SUBMISSIONS.value:
        return (ProjectActionStatus.FAIL, PROJECT_NOT_COLLECTING_SUBMISSIONS_MESSAGE)

    if project.submission_due_date > timezone.now():
        return (ProjectActionStatus.FAIL, FUTURE_SUBMISSION_DUE_DATE_MESSAGE)

    if submissions_count <= num_evaluations:
        message = f"Not enough submissions to assign {num_evaluations} peer reviews each."
        return (ProjectActionStatus.FAIL, message)

    return None


def _open_peer_review_window(project) -> None:
    # Closing submissions deterministically starts a fresh seven-day review window.
    project.peer_review_due_date = ceil_to_next_hour(timezone.now() + PEER_REVIEW_WINDOW)
    project.state = ProjectState.PEER_REVIEWING.value
    project.save()


def select_random_assignment(
    submissions: list[ProjectSubmission],
    num_projects_to_review: int,
    seed: int = 1,
) -> list[PeerReview]:
    """Build one review slot per reviewer: nobody reviews themselves, slots do not repeat."""
    num_submissions = len(submissions)
    if num_submissions <= num_projects_to_review:
        raise ValueError(
            "The number of projects to review should be greater than the number of submissions. "
            f"Number of projects to review: {num_projects_to_review}, "
            f"Number of submissions: {num_submissions}"
        )
    random.seed(seed)

    submissions = list(submissions)
    slot_pools = [list(range(num_submissions)) for _ in range(num_projects_to_review)]
    assignments: list[PeerReview] = []
    for reviewer_idx, reviewer_submission in enumerate(submissions):
        selected = {reviewer_idx}
        for slot_pool in slot_pools:
            available = [idx for idx in slot_pool if idx not in selected]
            if not available:
                available = [idx for idx in range(num_submissions) if idx not in selected]
            chosen_idx = random.choice(available)
            selected.add(chosen_idx)
            if chosen_idx in slot_pool:
                slot_pool.remove(chosen_idx)
            assignments.append(
                PeerReview(
                    submission_under_evaluation=submissions[chosen_idx],
                    reviewer=reviewer_submission,
                    state=PeerReviewState.TO_REVIEW.value,
                    optional=False,
                )
            )
    return assignments


def assign_peer_reviews_for_project(project) -> tuple[ProjectActionStatus, str]:
    """Assign the required review graph and move the project into PEER_REVIEWING."""
    with transaction.atomic():
        submissions = list(
            ProjectSubmission.objects.filter(
                project=project, volunteer_review_only=False
            ).select_related("enrollment")
        )
        num_evaluations = project.number_of_peers_to_evaluate
        failure = _assignment_precondition_failure(project, len(submissions), num_evaluations)
        if failure is not None:
            hooks.peer_reviews_assignment_failed(project=project, reason=failure[1])
            return failure

        assignments = select_random_assignment(submissions, num_evaluations, seed=ASSIGNMENT_SEED)
        PeerReview.objects.bulk_create(assignments)
        _open_peer_review_window(project)

    hooks.peer_reviews_assigned(project=project, review_count=len(assignments))
    return (
        ProjectActionStatus.OK,
        f"Peer reviews assigned for project {project.id} and state updated to 'PEER_REVIEWING'.",
    )


def ensure_volunteer_reviewer_submission(
    project,
    user,
    *,
    github_link: str = VOLUNTEER_GITHUB_LINK,
    commit_id: str = VOLUNTEER_COMMIT_ID,
) -> ProjectSubmission:
    """Volunteers review through a placeholder submission without a real project.

    The placeholder link is site-branded; sites may pass their own values.
    """
    submission = ProjectSubmission.objects.filter(
        project=project, student=user, volunteer_review_only=True
    ).first()
    if submission is not None:
        return submission

    enrollment, _ = Enrollment.objects.get_or_create(user=user, cohort=project.cohort)
    submission, _ = ProjectSubmission.objects.get_or_create(
        project=project,
        student=user,
        volunteer_review_only=True,
        defaults={
            "enrollment": enrollment,
            "github_link": github_link,
            "commit_id": commit_id,
        },
    )
    return submission


def add_volunteer_peer_review(
    project, user, submission_under_evaluation
) -> tuple[PeerReview, bool]:
    reviewer_submission = ensure_volunteer_reviewer_submission(project, user)
    if reviewer_submission.id == submission_under_evaluation.id:
        raise ValidationError("A reviewer cannot review their own submission.")

    review, created = PeerReview.objects.get_or_create(
        submission_under_evaluation=submission_under_evaluation,
        reviewer=reviewer_submission,
        optional=True,
    )
    if created:
        hooks.optional_review_added(project=project, review=review)
    return review, created


def remove_volunteer_peer_review(project, user, review_id) -> int:
    reviewer_submission = ProjectSubmission.objects.filter(project=project, student=user).first()
    if reviewer_submission is None:
        return 0
    deleted_count, _ = PeerReview.objects.filter(
        id=review_id, reviewer=reviewer_submission, optional=True
    ).delete()
    if deleted_count:
        hooks.optional_review_deleted(project=project, review_id=review_id)
    return deleted_count


def validate_project_criteria_answers(review_criteria, answers_by_criteria_id) -> None:
    """Reject forged, stale, or cross-project criterion identifiers upfront."""
    allowed_ids = {str(criteria.id) for criteria in review_criteria}
    posted_ids = {str(criteria_id) for criteria_id in answers_by_criteria_id}
    if posted_ids - allowed_ids:
        raise ProjectCriteriaValidationError(
            "The review contains a criterion that is not assigned to this project."
        )


def save_project_criteria_responses(review, review_criteria, answers_by_criteria_id) -> None:
    answers = {str(criteria_id): answer for criteria_id, answer in answers_by_criteria_id.items()}
    for criteria in review_criteria:
        CriteriaResponse.objects.update_or_create(
            review=review,
            criteria=criteria,
            defaults={"answer": answers.get(str(criteria.id))},
        )


def submit_peer_review(
    review: PeerReview,
    answers_by_criteria_id,
    *,
    learning_in_public_links: list[str] | None = None,
    time_spent_reviewing: float | None = None,
    problems_comments: str = "",
    note_to_peer: str = "",
) -> PeerReview:
    """Record criteria responses and mark the review SUBMITTED; idempotent per review."""
    project = review.submission_under_evaluation.project
    review_criteria = tuple(project.criteria_for_project())
    validate_project_criteria_answers(review_criteria, answers_by_criteria_id)

    with transaction.atomic():
        save_project_criteria_responses(review, review_criteria, answers_by_criteria_id)
        if project.learning_in_public_cap_review > 0 and learning_in_public_links is not None:
            review.learning_in_public_links = clean_learning_in_public_links(
                learning_in_public_links, project.learning_in_public_cap_review
            )
        if project.time_spent_evaluation_field and time_spent_reviewing is not None:
            review.time_spent_reviewing = time_spent_reviewing
        if project.problems_comments_field:
            review.problems_comments = (problems_comments or "").strip()
        review.note_to_peer = (note_to_peer or "").strip()
        review.submitted_at = timezone.now()
        review.state = PeerReviewState.SUBMITTED.value
        review.save()
    return review


@dataclass(frozen=True)
class PeerReviewGroupData:
    responses_by_review: dict
    submissions: dict
    reviews_by_submission: dict
    reviews_by_reviewer: dict


def criteria_responses_by_review(peer_reviews) -> dict:
    criteria_responses = CriteriaResponse.objects.filter(review__in=peer_reviews).select_related(
        "criteria"
    )
    responses_by_review = defaultdict(list)
    for response in criteria_responses:
        responses_by_review[response.review_id].append(response)
    return responses_by_review


def group_peer_reviews(peer_reviews) -> PeerReviewGroupData:
    """Group reviews by target submission and reviewer, keeping only SUBMITTED reviews."""
    responses_by_review = criteria_responses_by_review(peer_reviews)
    submissions = {}
    reviews_by_submission = {}
    reviews_by_reviewer = {}
    group_data = PeerReviewGroupData(
        responses_by_review=responses_by_review,
        submissions=submissions,
        reviews_by_submission=reviews_by_submission,
        reviews_by_reviewer=reviews_by_reviewer,
    )

    for review in peer_reviews:
        submission = review.submission_under_evaluation
        submissions[submission.id] = submission
        reviews_by_submission.setdefault(submission.id, [])
        reviews_by_reviewer.setdefault(review.reviewer_id, [])
        if review.state != PeerReviewState.SUBMITTED.value:
            continue
        reviews_by_submission[submission.id].append(review)
        reviews_by_reviewer[review.reviewer_id].append(review)
        review.responses = responses_by_review[review.id]

    return group_data


def calculate_median_score(
    submission: ProjectSubmission,
    evaluation_criteria: list[ReviewCriteria],
) -> tuple[int, list[ProjectEvaluationScore]]:
    """Fallback rollup with no submitted reviews: the rubric's own median per criterion."""
    total_score = 0
    scores = []
    for criteria in evaluation_criteria:
        median_score = criteria.median_score()
        score = ProjectEvaluationScore(
            submission=submission,
            review_criteria=criteria,
            score=median_score,
        )
        scores.append(score)
        total_score += median_score
    return total_score, scores


def responses_grouped_by_criteria(reviews: list[PeerReview]) -> dict:
    responses_by_criteria = defaultdict(list)
    for review in reviews:
        for response in review.responses:
            responses_by_criteria[response.criteria_id].append(response)
    return responses_by_criteria


def score_project_criteria(
    submission: ProjectSubmission,
    responses: list[CriteriaResponse],
) -> tuple[int, ProjectEvaluationScore]:
    criteria = responses[0].criteria
    scores = [response.get_score() for response in responses]
    criteria_score = math.ceil(statistics.median(scores))
    evaluation_score = ProjectEvaluationScore(
        submission=submission,
        review_criteria=criteria,
        score=criteria_score,
    )
    return criteria_score, evaluation_score


def calculate_project_score(
    submission: ProjectSubmission,
    evaluation_criteria,
    reviews: list[PeerReview],
) -> tuple[int, list[ProjectEvaluationScore]]:
    """Median of reviewer scores per criterion, summed over the rubric."""
    if len(reviews) == 0:
        logger.info("No reviews found for submission %s", submission.id)
        return calculate_median_score(submission, list(evaluation_criteria))

    new_evaluations: list[ProjectEvaluationScore] = []
    project_score = 0
    for responses in responses_grouped_by_criteria(reviews).values():
        criteria_score, evaluation = score_project_criteria(submission, responses)
        new_evaluations.append(evaluation)
        project_score += criteria_score
    return project_score, new_evaluations


def mandatory_reviews_count(reviewed) -> int:
    count = 0
    for review in reviewed:
        if not review.optional:
            count += 1
    return count


def project_faq_score(submission: ProjectSubmission) -> int:
    faq_url = submission.faq_contribution_url
    if faq_url and len(faq_url) >= 5:
        return 1
    return 0


def project_total_score(submission: ProjectSubmission) -> int:
    return (
        submission.project_score
        + submission.project_faq_score
        + submission.project_learning_in_public_score
        + submission.peer_review_score
        + submission.peer_review_learning_in_public_score
    )


def assign_peer_review_scores(submission: ProjectSubmission, project, reviewed) -> int:
    mandatory_count = mandatory_reviews_count(reviewed)
    submission.peer_review_score = mandatory_count * project.points_for_peer_review
    submission.peer_review_learning_in_public_score = peer_review_lip_score(
        submission, project, reviewed
    )
    submission.reviewed_enough_peers = mandatory_count >= project.number_of_peers_to_evaluate
    return mandatory_count


@dataclass(frozen=True)
class SubmissionScoringData:
    submission: ProjectSubmission
    project: object
    reviews: list
    reviewed: list
    criteria: object


def score_submission(data: SubmissionScoringData) -> list[ProjectEvaluationScore]:
    project_score, scores = calculate_project_score(
        submission=data.submission,
        evaluation_criteria=data.criteria,
        reviews=data.reviews,
    )
    data.submission.project_score = project_score

    assign_peer_review_scores(data.submission, data.project, data.reviewed)
    data.submission.project_learning_in_public_score = project_lip_score(
        data.submission, data.project
    )
    data.submission.project_faq_score = project_faq_score(data.submission)
    data.submission.total_score = project_total_score(data.submission)
    # The per-project threshold is the cohort's project_passing_score; the cohort-level
    # min_projects_to_pass counts passed projects for the course outcome.
    data.submission.passed = (
        data.submission.project_score >= data.project.points_to_pass
    ) and data.submission.reviewed_enough_peers
    return scores


@dataclass(frozen=True)
class ProjectScoringData:
    project: object
    submissions: dict
    reviews_by_submission: dict
    reviews_by_reviewer: dict
    criteria: object


@dataclass
class ProjectScoringResult:
    submissions_to_update: list
    evaluation_scores: list
    passed_count: int

    def record(self, submission, scores) -> None:
        self.evaluation_scores.extend(scores)
        self.submissions_to_update.append(submission)
        if submission.passed:
            self.passed_count += 1


def project_submission_scoring_data(data: ProjectScoringData, submission_id, submission):
    reviews = data.reviews_by_submission[submission_id]
    reviewed = data.reviews_by_reviewer.get(submission_id) or []
    return SubmissionScoringData(
        submission=submission,
        project=data.project,
        reviews=reviews,
        reviewed=reviewed,
        criteria=data.criteria,
    )


def score_project_submissions(data: ProjectScoringData) -> ProjectScoringResult:
    result = ProjectScoringResult(
        submissions_to_update=[],
        evaluation_scores=[],
        passed_count=0,
    )
    for submission_id, submission in data.submissions.items():
        submission_data = project_submission_scoring_data(data, submission_id, submission)
        scores = score_submission(submission_data)
        result.record(submission, scores)
    return result


def calculate_project_scoring(project, peer_reviews) -> ProjectScoringResult:
    group_data = group_peer_reviews(peer_reviews)
    scoring_data = ProjectScoringData(
        project=project,
        submissions=group_data.submissions,
        reviews_by_submission=group_data.reviews_by_submission,
        reviews_by_reviewer=group_data.reviews_by_reviewer,
        criteria=project.criteria_for_project(),
    )
    return score_project_submissions(scoring_data)


def _validate_project_scoreable(project) -> str | None:
    """Return an error message if the project can't be scored, else None."""
    if project.points_to_pass == 0:
        return (
            "Project has no points to pass. Update the cohort's `project_passing_score` "
            "field to a greater than zero value"
        )
    if project.state != ProjectState.PEER_REVIEWING.value:
        return "Project is not in 'PEER_REVIEWING' state"
    if project.peer_review_due_date > timezone.now():
        return (
            "The peer review due date is in the future. Update the due date to score the project."
        )
    return None


def _peer_reviews_for_project(project):
    return PeerReview.objects.filter(
        submission_under_evaluation__project=project,
    ).select_related(
        "submission_under_evaluation",
        "submission_under_evaluation__enrollment",
        "reviewer",
    )


def _project_scoreable_peer_reviews(project):
    error = _validate_project_scoreable(project)
    if error is not None:
        return None, error

    peer_reviews = _peer_reviews_for_project(project)
    if peer_reviews.count() == 0:
        return None, "No peer reviews found for the project."
    return peer_reviews, None


def _replace_project_evaluation_scores(submission_ids, all_scores) -> None:
    ProjectEvaluationScore.objects.filter(submission_id__in=submission_ids).delete()
    ProjectEvaluationScore.objects.bulk_create(all_scores)


def _complete_scored_project(project, calculation: ProjectScoringResult) -> None:
    ProjectSubmission.objects.bulk_update(
        calculation.submissions_to_update,
        [
            "project_score",
            "project_faq_score",
            "project_learning_in_public_score",
            "peer_review_score",
            "peer_review_learning_in_public_score",
            "total_score",
            "reviewed_enough_peers",
            "passed",
        ],
    )
    submission_ids = [submission.id for submission in calculation.submissions_to_update]
    _replace_project_evaluation_scores(submission_ids, calculation.evaluation_scores)

    project.state = ProjectState.COMPLETED.value
    project.save()
    # Donor parity: the leaderboard refresh runs inside the scoring transaction.
    hooks.project_leaderboard_updater(project=project)


def score_project(project) -> tuple[ProjectActionStatus, str]:
    """Score every submission reachable from the project's reviews and close the project."""
    with transaction.atomic():
        peer_reviews, error = _project_scoreable_peer_reviews(project)
        if error is not None:
            hooks.project_scoring_failed(project=project, reason=error)
            return (ProjectActionStatus.FAIL, error)

        calculation = calculate_project_scoring(project, peer_reviews)
        passed_ratio = calculation.passed_count / len(calculation.submissions_to_update)
        _complete_scored_project(project, calculation)

    hooks.project_scored(project=project, passed_count=calculation.passed_count)
    message = (
        f"Project {project.id} scored and state updated to "
        f"'COMPLETED'. {calculation.passed_count} passed "
        f"({passed_ratio:.2f})."
    )
    return (ProjectActionStatus.OK, message)
