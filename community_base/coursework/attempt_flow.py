"""The learner's side of a project attempt, independent of the host's models and routes.

Extracted from AI Shipping Labs (``attempt_nav``, ``learner_attempt_phases``,
``project_criteria_page``) so both sites build the same attempt sidebar, status rows and
Evaluation criteria page. Everything here is pure: the host passes its own submissions,
reviews and URL builders, and renders the results in its own design.

- ``attempt_nav_items``: the attempt's sidebar sub-steps -- Submit, ``Review N: <peer>`` for
  every assigned review, then Feedback once the attempt is in its feedback phase.
- ``learner_attempt_phases``: ``{project_key: AttemptPhase}`` for one learner across attempts,
  scored from the reviews the learner's submission received.
- ``phase_row``: badge, tone, link, action and date for one attempt row.
- ``criteria_page_context``: the rubric of a course's attempts plus a pointer to the attempt the
  learner can still submit.
- ``review_heading``: "Evaluate <peer>'s submission" with the peer's pseudonym and the project
  description the submitter wrote.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from community_base.coursework.peer_pseudonym import peer_pseudonym
from community_base.coursework.project_criteria import (
    criteria_summary,
    is_review_complete,
    settle_completion,
)
from community_base.coursework.project_phase import FEEDBACK, MISSED, REVIEWS_URL, attempt_phase
from community_base.coursework.project_results import project_result

SUBMIT_PAGE, REVIEW_PAGE, FEEDBACK_PAGE, CRITERIA_PAGE = "submit", "review", "feedback", "criteria"
OPEN_BADGE = "open"


@dataclass(frozen=True)
class AttemptNavItem:
    key: str
    title: str
    url: str
    done: bool
    current: bool


def _submitter_id(submission):
    for name in ("user_id", "student_id"):
        value = getattr(submission, name, None)
        if value is not None:
            return value
    return None


def _reviewed_submission(review):
    for name in ("submission", "submission_under_evaluation"):
        value = getattr(review, name, None)
        if value is not None:
            return value
    return None


def peer_name(review, course_id) -> str:
    """The pseudonym of the learner whose submission ``review`` evaluates."""
    return peer_pseudonym(_submitter_id(_reviewed_submission(review)), course_id)


def attempt_nav_items(
    phase,
    *,
    has_submission: bool,
    assigned_reviews: Iterable,
    course_id,
    submit_url: str,
    review_url: Callable[[object], str],
    feedback_url: str = "",
    page: str = "",
    current_review_id=None,
) -> tuple[AttemptNavItem, ...]:
    """Submit, one ``Review N: <peer>`` per assigned review, then Feedback in the feedback phase.

    ``page`` is the attempt page being shown (``SUBMIT_PAGE``, ``REVIEW_PAGE``, ``FEEDBACK_PAGE``)
    and ``current_review_id`` the review open on a review page.
    """
    items = [
        AttemptNavItem(
            key="submit",
            title="Submit",
            url=submit_url,
            done=has_submission,
            current=page == SUBMIT_PAGE,
        )
    ]
    for number, review in enumerate(assigned_reviews, start=1):
        items.append(
            AttemptNavItem(
                key="review",
                title=f"Review {number}: {peer_name(review, course_id)}",
                url=review_url(review),
                done=is_review_complete(review),
                current=page == REVIEW_PAGE and review.pk == current_review_id,
            )
        )
    if phase is not None and phase.key == FEEDBACK and feedback_url:
        items.append(
            AttemptNavItem(
                key="feedback",
                title="Feedback",
                url=feedback_url,
                done=phase.results_final,
                current=page == FEEDBACK_PAGE,
            )
        )
    return tuple(items)


def _criteria(criteria_for, project) -> list[dict]:
    return list(criteria_for(project) or [])


def learner_attempt_phases(
    projects: Iterable,
    *,
    submissions: Mapping,
    assigned: Mapping,
    received: Mapping,
    criteria_for: Callable[[object], list[dict]],
    now,
    passing_score: int = 0,
) -> dict:
    """``{project.pk: AttemptPhase}`` for one learner.

    ``submissions`` maps ``project.pk`` to the learner's submission, ``assigned`` maps it to the
    reviews the learner must write (in display order) and ``received`` maps a submission pk to
    the reviews that submission received. Reviews missing a required answer count as incomplete.
    """
    phases = {}
    for project in projects:
        criteria = _criteria(criteria_for, project)
        submission = submissions.get(project.pk)
        project_assigned = settle_completion(assigned.get(project.pk, []), criteria)
        result = None
        if submission is not None:
            got = [
                review
                for review in settle_completion(received.get(submission.pk, []), criteria)
                if is_review_complete(review)
            ]
            done = sum(1 for review in project_assigned if is_review_complete(review))
            reviewed_enough = bool(project_assigned) and done == len(project_assigned)
            result = project_result(criteria, got, passing_score, reviewed_enough)
        phases[project.pk] = attempt_phase(project, submission, project_assigned, now, result)
    return phases


def phase_row(phase, *, submit_url: str, reviews_url: str, when=None) -> dict:
    """Badge, tone, link, action and date of one attempt row."""
    url, action = "", ""
    if phase.key != MISSED:
        url = reviews_url if phase.action_url_name == REVIEWS_URL else submit_url
        action = phase.action_label or "View project"
    return {
        "status": phase.badge_label,
        "status_key": phase.badge_key,
        "status_tone": phase.badge_tone,
        "url": url,
        "action": action,
        "when": phase.deadline if phase.deadline is not None else when,
    }


def criteria_page_context(
    projects: Iterable,
    *,
    criteria_for: Callable[[object], list[dict]],
    phases: Mapping | None = None,
) -> dict | None:
    """The rubric shown on the Evaluation criteria page, or None when no attempt has criteria.

    The first attempt (in the given order) with criteria supplies the rubric; ``open_project``
    is the first attempt the learner can still submit (badge "Open"), for a single call to action.
    """
    projects = list(projects)
    criteria_project = next((p for p in projects if _criteria(criteria_for, p)), None)
    if criteria_project is None:
        return None
    phases = phases or {}
    open_project = next(
        (
            project
            for project in projects
            if getattr(phases.get(project.pk), "badge_key", None) == OPEN_BADGE
        ),
        None,
    )
    return {
        "criteria_project": criteria_project,
        "project_criteria": criteria_summary(_criteria(criteria_for, criteria_project)),
        "open_project": open_project,
    }


def review_heading(review, course_id) -> dict:
    """Heading data for a review page: the peer's pseudonym and the submitter's description."""
    submission = _reviewed_submission(review)
    name = peer_name(review, course_id)
    return {
        "peer_name": name,
        "heading": f"Evaluate {name}'s submission",
        "description": str(getattr(submission, "description", "") or "").strip(),
    }
