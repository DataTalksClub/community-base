"""Staff-driven project state transitions."""

import logging

from community_base.coursework.models import PROJECT_STATE_LABELS, ProjectState
from community_base.kernel.redaction import redact

logger = logging.getLogger(__name__)


class ProjectStateError(ValueError):
    """The requested state change is not allowed."""


def parse_state(value) -> ProjectState:
    """Resolve a ProjectState from its code ('PR'), name ('peer_reviewing'), or label."""
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    for state in ProjectState:
        label = PROJECT_STATE_LABELS[state.value].lower().replace(" ", "_")
        if text in (state.value.lower(), state.name.lower(), label):
            return state
    valid = ", ".join(s.name.lower() for s in ProjectState)
    raise ProjectStateError(f'Unknown state "{value}". Use one of: {valid}.')


def _is_self_paced(project) -> bool:
    if hasattr(project, "uses_pooled_review"):
        return bool(project.uses_pooled_review)
    return bool(getattr(project, "is_self_paced", False))


def set_project_state(project, state, *, actor=None) -> str:
    """Move ``project`` to ``state``; returns the previous state code."""
    target = ProjectState(state)
    if _is_self_paced(project):
        raise ProjectStateError("Self-paced attempts have no project state.")
    previous = project.state
    if previous == target.value:
        return previous
    if target == ProjectState.COMPLETED and previous != ProjectState.PEER_REVIEWING.value:
        prev_label = PROJECT_STATE_LABELS.get(previous, previous)
        raise ProjectStateError(
            f"Only a project in Peer reviewing can be completed (it is {prev_label})."
        )
    project.state = target.value
    project.save(update_fields=["state"])
    course_ref = getattr(project, "cohort_id", None) or getattr(project, "course_id", None)
    actor_label = redact(getattr(actor, "email", None) or "system")
    logger.info(
        "Project state changed: scope=%s project=%s %s -> %s by %s",
        course_ref,
        project.slug,
        previous,
        target.value,
        actor_label,
    )
    return previous
