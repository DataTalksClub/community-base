"""Per-learner homework state shared by host navigation and homework pages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from community_base.homework_steps.models import HomeworkDraft
from community_base.homework_steps.types import AcceptedSubmission

HomeworkStateValue = Literal[
    "not_submitted",
    "draft",
    "submitted",
    "unsubmitted_changes",
    "closed_not_submitted",
    "scored",
]

_LABELS = {
    "not_submitted": "Not submitted",
    "draft": "Draft",
    "submitted": "Submitted",
    "unsubmitted_changes": "Unsubmitted changes",
    "closed_not_submitted": "Closed — not submitted",
    "scored": "Scored",
}


@dataclass(frozen=True)
class LearnerHomeworkState:
    """Display-ready state for one learner and one assignment."""

    value: HomeworkStateValue
    label: str
    aria_label: str
    availability: str
    has_submission: bool
    has_saved_draft: bool
    has_pending_changes: bool
    submitted_at: datetime | None = None


def accepted_submission_for(assignment, *, submitted=False):
    """Return the explicit snapshot, or adapt the v0.5.10 accepted-answer fields."""

    if assignment.accepted_submission is not None:
        return assignment.accepted_submission
    context = assignment.context if isinstance(assignment.context, dict) else {}
    if assignment.has_submission or context.get("homework_is_submitted") or submitted:
        return AcceptedSubmission(
            answers=assignment.existing_answers,
            final_fields=assignment.existing_final_fields,
        )
    return None


def _normal_answers(assignment, answers):
    result = {}
    for question in assignment.questions:
        value = answers.get(question.key)
        if question.type == "checkbox":
            if value in (None, "", []):
                result[question.key] = ()
            else:
                values = value if isinstance(value, (list, tuple)) else [value]
                result[question.key] = tuple(sorted(str(item) for item in values))
        else:
            result[question.key] = "" if value is None else value
    return result


def _normal_fields(assignment, values):
    return {field.key: values.get(field.key) or "" for field in assignment.final_fields}


def _has_content(assignment, answers, final_fields):
    return any(
        value not in ("", ()) for value in _normal_answers(assignment, answers).values()
    ) or any(value != "" for value in _normal_fields(assignment, final_fields).values())


def _matches_snapshot(assignment, answers, final_fields, accepted):
    return _normal_answers(assignment, answers) == _normal_answers(
        assignment, accepted.answers
    ) and _normal_fields(assignment, final_fields) == _normal_fields(
        assignment, accepted.final_fields
    )


def changed_snapshot_keys(assignment, answers, final_fields, accepted):
    """Return changed question and final-field keys for a separate unsent-draft view."""

    accepted_answers = _normal_answers(assignment, accepted.answers)
    draft_answers = _normal_answers(assignment, answers)
    accepted_fields = _normal_fields(assignment, accepted.final_fields)
    draft_fields = _normal_fields(assignment, final_fields)
    return (
        {key for key in draft_answers if draft_answers[key] != accepted_answers[key]},
        {key for key in draft_fields if draft_fields[key] != accepted_fields[key]},
    )


def calculate_homework_state(
    assignment,
    *,
    draft_answers=None,
    draft_final_fields=None,
    draft_exists=False,
    accepted_submission=None,
):
    """Calculate the six learner-facing states without reading or writing the database."""

    availability = assignment.availability
    if availability not in ("open", "closed", "scored"):
        raise ValueError("Homework availability must be open, closed, or scored")
    draft_answers = draft_answers or {}
    draft_final_fields = draft_final_fields or {}
    accepted = accepted_submission or accepted_submission_for(assignment)
    has_submission = accepted is not None
    has_draft_content = _has_content(assignment, draft_answers, draft_final_fields)
    has_pending_changes = bool(
        has_submission
        and draft_exists
        and not _matches_snapshot(assignment, draft_answers, draft_final_fields, accepted)
    )
    has_saved_draft = has_pending_changes if has_submission else has_draft_content

    if availability == "open":
        if not has_submission:
            value = "draft" if has_saved_draft else "not_submitted"
        else:
            value = "unsubmitted_changes" if has_pending_changes else "submitted"
    elif availability == "scored" and has_submission:
        value = "scored"
    elif has_submission:
        value = "submitted"
    else:
        value = "closed_not_submitted"

    label = _LABELS[value]
    return LearnerHomeworkState(
        value=value,
        label=label,
        aria_label=f"Homework status: {label}",
        availability=availability,
        has_submission=has_submission,
        has_saved_draft=has_saved_draft,
        has_pending_changes=has_pending_changes,
        submitted_at=accepted.submitted_at if accepted else None,
    )


def homework_state_for(user, assignment):
    """Read one learner's saved draft and return state without creating a draft row."""

    if not getattr(user, "is_authenticated", False):
        raise ValueError("Homework state is available only to an authenticated learner")
    draft = (
        HomeworkDraft.objects.filter(user=user, assignment_key=assignment.key)
        .only("answers", "final_fields")
        .first()
    )
    return calculate_homework_state(
        assignment,
        draft_answers=draft.answers if draft else {},
        draft_final_fields=draft.final_fields if draft else {},
        draft_exists=draft is not None,
    )
