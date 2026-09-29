"""One learner's row in a course page Projects table: stage, badge, pill, link and deadline.

This is the course management platform's learner-facing project presentation
(``courses/views/course_projects.py`` ``update_project_with_additional_info`` and the Projects
table of ``courses/templates/courses/course.html``), moved here unchanged in behaviour so both
sites render a project from one owner. The labels are CMP's and are kept as they are:

=====  ==============  =====================================================================
State  Not submitted   Submitted
=====  ==============  =====================================================================
``CL`` Closed          Closed
``CS`` Open            Submitted
``PR`` Not submitted   Review, then Review completed once the learner's completed required
                       reviews reach ``number_of_peers_to_evaluate``
``CO`` Not submitted   Passed ({score}) or Failed ({score})
=====  ==============  =====================================================================

The link follows the stage, submitted or not, as in CMP: ``CS`` links the submission page,
``PR`` the peer review page, ``CO`` the results page, and ``CL`` has no link.

Pooled (self-paced) projects never leave ``CS`` or ``CL`` at the project level (see the README's
"Assessment modes"), so a submitted learner's stage comes from their own
``ProjectSubmission.review_state`` instead: awaiting assignment reads as ``CS``, in review as
``PR`` and scored as ``CO``. A closed project reads Closed in both modes, as CMP has it.

``project_row`` only reads attributes (``state``, the two due dates,
``number_of_peers_to_evaluate``; ``submitted_at``, ``total_score``, ``passed`` and, for a pooled
project, ``review_state``), so a site still serving its own project rows with the same state
codes can call it before adopting the package models.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from django.db.models import Count, Min, Prefetch, Q

from community_base.coursework.models import (
    PeerReviewState,
    Project,
    ProjectState,
    ProjectSubmission,
    SubmissionReviewState,
)

# Pill surfaces: what a state asks of the reader. A site maps each to its own styling, and uses
# the same four for homework so one word never wears two pills.
PAST = "past"  # over, nothing gained and nothing left to do: closed, never submitted, failed
YOUR_MOVE = "your_move"  # open to the learner now: an open deadline, reviews still owed
DONE = "done"  # the learner did their part and waits on the course: submitted, reviews delivered
RESULT = "result"  # a number came back: passed

LINK_SUBMIT = "submit"
LINK_EVAL = "eval"
LINK_RESULTS = "results"

DEADLINE_SUBMISSION = "submission"
DEADLINE_PEER_REVIEW = "peer_review"

_CLOSED = ProjectState.CLOSED.value
_COLLECTING = ProjectState.COLLECTING_SUBMISSIONS.value
_REVIEWING = ProjectState.PEER_REVIEWING.value
_COMPLETED = ProjectState.COMPLETED.value

_POOLED_STAGE = {
    SubmissionReviewState.AWAITING_ASSIGNMENT.value: _COLLECTING,
    SubmissionReviewState.IN_REVIEW.value: _REVIEWING,
    SubmissionReviewState.SCORED.value: _COMPLETED,
}

_LINK_FOR_STAGE = {
    _COLLECTING: LINK_SUBMIT,
    _REVIEWING: LINK_EVAL,
    _COMPLETED: LINK_RESULTS,
}


@dataclass(frozen=True)
class ProjectBadge:
    """The words, CMP's badge class, the pill surface, and the score behind them."""

    label: str
    css_class: str
    surface: str
    score: int | None = None


@dataclass(frozen=True)
class ProjectRow:
    """Everything a Projects table row shows for one learner and one project.

    ``css_class`` is CMP's badge class (``bg-success`` and so on), kept for screens that still
    style by it. ``completed`` is true where CMP shows "Completed" instead of a countdown.
    ``href`` is set only by a builder given a site URL resolver.
    """

    project: object
    stage: str
    submitted: bool
    submitted_at: datetime | None
    label: str
    css_class: str
    surface: str
    score: int | None
    link_target: str | None
    deadline: datetime | None
    deadline_kind: str | None
    completed: bool
    href: str | None = None


def project_stage(project, submission) -> str:
    """The lifecycle stage this learner sees: the project's state, or a pooled learner's own."""

    if submission is None or project.state == _CLOSED:
        return project.state
    if not getattr(project, "uses_pooled_review", False):
        return project.state
    return _POOLED_STAGE.get(submission.review_state, project.state)


def _unsubmitted_badge(stage) -> ProjectBadge:
    if stage == _CLOSED:
        return ProjectBadge("Closed", "bg-secondary", PAST)
    if stage == _COLLECTING:
        return ProjectBadge("Open", "bg-warning", YOUR_MOVE)
    return ProjectBadge("Not submitted", "bg-secondary", PAST)


def _review_badge(project, completed_reviews) -> ProjectBadge:
    if completed_reviews >= project.number_of_peers_to_evaluate:
        return ProjectBadge("Review completed", "bg-success", DONE)
    return ProjectBadge("Review", "bg-danger", YOUR_MOVE)


def _completed_badge(submission) -> ProjectBadge:
    score = submission.total_score
    if submission.passed:
        return ProjectBadge(f"Passed ({score})", "bg-success", RESULT, score)
    return ProjectBadge(f"Failed ({score})", "bg-secondary", PAST, score)


def project_badge(project, submission, stage, completed_reviews) -> ProjectBadge:
    """CMP's badge for a stage; a closed project keeps its Closed badge once submitted."""

    if submission is None:
        return _unsubmitted_badge(stage)
    if stage == _COLLECTING:
        return ProjectBadge("Submitted", "bg-info", DONE)
    if stage == _REVIEWING:
        return _review_badge(project, completed_reviews)
    if stage == _COMPLETED:
        return _completed_badge(submission)
    return _unsubmitted_badge(stage)


def _pooled_deadline(stage, review_due_at):
    """A self-paced learner has no submission deadline, only their batch's review ``due_at``."""

    if stage == _COMPLETED:
        return review_due_at, DEADLINE_PEER_REVIEW, True
    if stage == _REVIEWING and review_due_at is not None:
        return review_due_at, DEADLINE_PEER_REVIEW, False
    return None, None, False


def _deadline(project, stage, submitted, review_due_at):
    """CMP's Deadline column: the review due date once reviewing a submission, else submission.

    A pooled (self-paced) project shows no deadline until the learner is in a batch (#323).
    """

    if getattr(project, "uses_pooled_review", False):
        return _pooled_deadline(stage, review_due_at)
    review_due = review_due_at or project.peer_review_due_date
    if stage == _REVIEWING and submitted:
        return review_due, DEADLINE_PEER_REVIEW, False
    if stage == _COMPLETED:
        return review_due, DEADLINE_PEER_REVIEW, True
    return project.submission_due_date, DEADLINE_SUBMISSION, False


def project_row(project, submission, *, completed_reviews: int, review_due_at=None) -> ProjectRow:
    """The learner's row for one project.

    ``submission`` is the learner's own submission or ``None``. ``completed_reviews`` counts the
    learner's non-optional reviews of others in state ``SU``. ``review_due_at`` is a pooled
    learner's batch deadline; without it a dated project's ``peer_review_due_date`` is shown and
    a pooled project shows no deadline (``deadline`` and ``deadline_kind`` are ``None``).
    """

    stage = project_stage(project, submission)
    submitted = submission is not None
    badge = project_badge(project, submission, stage, completed_reviews)
    deadline, deadline_kind, completed = _deadline(project, stage, submitted, review_due_at)
    return ProjectRow(
        project=project,
        stage=stage,
        submitted=submitted,
        submitted_at=getattr(submission, "submitted_at", None),
        label=badge.label,
        css_class=badge.css_class,
        surface=badge.surface,
        score=badge.score,
        link_target=_LINK_FOR_STAGE.get(stage),
        deadline=deadline,
        deadline_kind=deadline_kind,
        completed=completed,
    )


def _learner_submissions(user):
    if not user.is_authenticated:
        return ProjectSubmission.objects.none()
    required = Q(reviewers__optional=False)
    return ProjectSubmission.objects.filter(student=user).annotate(
        completed_reviews_count=Count(
            "reviewers",
            filter=required & Q(reviewers__state=PeerReviewState.SUBMITTED.value),
        ),
        review_due_at=Min("reviewers__batch__due_at", filter=required),
    )


def _row_from_prefetch(project, url_for) -> ProjectRow:
    submission = None
    completed_reviews = 0
    review_due_at = None
    if project.learner_submissions:
        submission = project.learner_submissions[0]
        completed_reviews = submission.completed_reviews_count
        review_due_at = submission.review_due_at
    row = project_row(
        project, submission, completed_reviews=completed_reviews, review_due_at=review_due_at
    )
    if url_for is None or row.link_target is None:
        return row
    return replace(row, href=url_for(project, row.link_target))


def project_rows_for_cohort(cohort, user, *, url_for=None) -> list[ProjectRow]:
    """Every project of a cohort as this learner's rows, ordered by id as CMP orders them.

    Two queries however many projects there are. ``url_for(project, link_target)`` is the site's
    resolver for ``submit``, ``eval`` and ``results``; routes stay with the site.
    """

    projects = (
        Project.objects.filter(cohort=cohort)
        .select_related("cohort")
        .prefetch_related(
            Prefetch(
                "submissions",
                queryset=_learner_submissions(user),
                to_attr="learner_submissions",
            )
        )
        .order_by("id")
    )
    rows = []
    for project in projects:
        rows.append(_row_from_prefetch(project, url_for))
    return rows
