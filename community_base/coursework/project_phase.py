"""Which phase a learner is in for one project attempt (pure, no DB access)."""

from dataclasses import dataclass

from community_base.coursework.models import ProjectState, SubmissionReviewState
from community_base.coursework.project_criteria import is_review_complete, points_label

SUBMIT, WAITING, REVIEW, FEEDBACK, MISSED = (
    "submit",
    "waiting",
    "review",
    "feedback",
    "missed",
)
PHASE_LABELS = {
    SUBMIT: "Open",
    WAITING: "Waiting for reviews",
    REVIEW: "Peer review",
    FEEDBACK: "Feedback",
    MISSED: "Missed",
}
SUBMIT_URL, REVIEWS_URL = "course_project_submit", "course_project_reviews"
STEP_ORDER = ((SUBMIT, "Submit"), (REVIEW, "Peer review"), (FEEDBACK, "Feedback"))
_CURRENT_STEP = {SUBMIT: 0, MISSED: 0, WAITING: 1, REVIEW: 1, FEEDBACK: 2}
FINAL_SUBMISSION_STATUSES = ("review_complete", "certified", SubmissionReviewState.SCORED.value)
BADGE_TONES = {
    "open": "warning",
    "not_submitted": "muted",
    "closed": "muted",
    "submitted": "info",
    "review": "warning",
    "review_completed": "success",
    "passed": "success",
    "failed": "muted",
    "scored": "info",
}


@dataclass(frozen=True)
class PhaseStep:
    key: str
    label: str
    state: str
    url_name: str
    anchor: str


@dataclass(frozen=True)
class AttemptPhase:
    key: str
    label: str
    badge_key: str
    badge_label: str
    badge_tone: str
    deadline: object
    deadline_kind: str
    action_url_name: str
    action_label: str
    reviews_done: int
    reviews_assigned: int
    results_final: bool
    steps: tuple
    deadline_overdue: bool = False

    @property
    def reviews_pending(self) -> int:
        return self.reviews_assigned - self.reviews_done

    @property
    def certificate_blocked(self) -> bool:
        """Pending assigned reviews block the certificate."""
        return self.reviews_pending > 0


def _is_self_paced(project) -> bool:
    if hasattr(project, "uses_pooled_review"):
        return bool(project.uses_pooled_review)
    return bool(getattr(project, "is_self_paced", False))


def _submission_due_at(project):
    if hasattr(project, "submission_due_at"):
        return project.submission_due_at
    return getattr(project, "submission_due_date", None)


def _review_due_at(project):
    if hasattr(project, "review_due_at"):
        return project.review_due_at
    return getattr(project, "peer_review_due_date", None)


def _submission_status(submission):
    if hasattr(submission, "status"):
        return submission.status
    return getattr(submission, "review_state", None)


def _dated_phase_key(project, submission, assigned: int) -> str:
    state = project.state
    if state == ProjectState.COLLECTING_SUBMISSIONS.value:
        return SUBMIT
    if submission is None:
        return MISSED
    if state == ProjectState.COMPLETED.value:
        return FEEDBACK
    if state == ProjectState.PEER_REVIEWING.value and assigned:
        return REVIEW
    return WAITING


def _phase_key(project, submission, done: int, assigned: int) -> str:
    if not _is_self_paced(project):
        return _dated_phase_key(project, submission, assigned)
    if submission is None:
        return SUBMIT
    if assigned:
        return REVIEW if done < assigned else FEEDBACK
    return WAITING


def _results_final(project, submission, done: int, assigned: int) -> bool:
    if submission is None:
        return False
    if _is_self_paced(project):
        return done == assigned and _submission_status(submission) in FINAL_SUBMISSION_STATUSES
    return project.state == ProjectState.COMPLETED.value


def _final_badge(result) -> tuple[str, str]:
    if result.passed is None:
        return "scored", points_label(result.total)
    if result.passed:
        return "passed", f"Passed ({result.total})"
    return "failed", f"Failed ({result.total})"


def _badge(project, key: str, has_submission: bool, done: int, assigned: int, final: bool, result):
    if not _is_self_paced(project) and project.state == ProjectState.CLOSED.value:
        return "closed", "Closed"
    if key == SUBMIT:
        if has_submission:
            return "submitted", "Submitted"
        return "open", "Open"
    if key == MISSED:
        return "not_submitted", "Not submitted"
    if final and result is not None:
        return _final_badge(result)
    if assigned and done >= assigned:
        return "review_completed", "Review completed"
    if assigned:
        return "review", f"Review {done}/{assigned}"
    return "review", "Review"


def _deadline(project, key: str):
    if _is_self_paced(project) or key == MISSED:
        return None, ""
    if key == SUBMIT:
        return _submission_due_at(project), "submission"
    if key in (WAITING, REVIEW, FEEDBACK) and project.state == ProjectState.PEER_REVIEWING.value:
        return _review_due_at(project), "review"
    return None, ""


def _action(project, key: str, has_submission: bool, done: int, assigned: int) -> tuple[str, str]:
    if key == SUBMIT:
        if has_submission:
            return SUBMIT_URL, "Update submission"
        return SUBMIT_URL, "Submit project"
    if key == WAITING and _is_self_paced(project):
        return SUBMIT_URL, "Update submission"
    if key == REVIEW:
        if done >= assigned:
            return REVIEWS_URL, "View reviews"
        if done == 0:
            return REVIEWS_URL, "Start reviews"
        return REVIEWS_URL, "Continue reviews"
    if key == FEEDBACK:
        return REVIEWS_URL, "See feedback"
    return "", ""


def _step(index: int, key: str, label: str, current: int, phase_key: str) -> PhaseStep:
    state = "upcoming"
    if index < current:
        state = "done"
    elif index == current:
        state = "current"
    url_name, anchor = SUBMIT_URL, ""
    if key == REVIEW:
        url_name = ""
        if current >= 1:
            url_name = REVIEWS_URL
    elif key == FEEDBACK:
        url_name = ""
        if phase_key == FEEDBACK:
            url_name, anchor = REVIEWS_URL, "peer-feedback"
    return PhaseStep(key=key, label=label, state=state, url_name=url_name, anchor=anchor)


def phase_steps(phase_key: str) -> tuple[PhaseStep, ...]:
    current = _CURRENT_STEP[phase_key]
    return tuple(
        _step(index, key, label, current, phase_key)
        for index, (key, label) in enumerate(STEP_ORDER)
    )


def attempt_phase(project, submission, assigned_reviews, now, result=None) -> AttemptPhase:
    """The learner's phase for ``project``."""
    assigned = len(assigned_reviews)
    done = sum(1 for review in assigned_reviews if is_review_complete(review))
    key = _phase_key(project, submission, done, assigned)
    final = _results_final(project, submission, done, assigned)
    has_submission = submission is not None
    badge_key, badge_label = _badge(project, key, has_submission, done, assigned, final, result)
    deadline, deadline_kind = _deadline(project, key)
    overdue = deadline is not None and deadline <= now
    action_url_name, action_label = _action(project, key, has_submission, done, assigned)
    return AttemptPhase(
        key=key,
        label=PHASE_LABELS[key],
        badge_key=badge_key,
        badge_label=badge_label,
        badge_tone=BADGE_TONES[badge_key],
        deadline=deadline,
        deadline_kind=deadline_kind,
        action_url_name=action_url_name,
        action_label=action_label,
        reviews_done=done,
        reviews_assigned=assigned,
        results_final=final,
        steps=phase_steps(key),
        deadline_overdue=overdue,
    )
