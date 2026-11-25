"""Structured evaluation form for one assigned peer review."""

from django.utils import timezone

from community_base.coursework.project_criteria import (
    is_review_complete,
    normalize_stored_criteria,
    points_label,
    score_review,
)
from community_base.coursework.project_results import chosen_indexes, review_total

MISSING_CRITERIA_MESSAGE = "Choose an option for every criterion."


def missing_criteria_message(titles) -> str:
    return f"{MISSING_CRITERIA_MESSAGE} Missing: {', '.join(titles)}."


def _option_rows(criterion: dict, selected: dict, readonly: bool) -> list[dict]:
    picked = chosen_indexes(criterion, selected)
    rows = []
    for index, option in enumerate(criterion["options"]):
        rows.append(
            {
                "index": index,
                "label": f"{option['text']} ({points_label(option['points'])})",
                "text": option["text"],
                "points_label": points_label(option["points"]),
                "checked": index in picked,
                "readonly": readonly,
            }
        )
    return rows


def _criterion_row(number: int, criterion: dict, selected: dict, missing, readonly: bool) -> dict:
    input_type = "radio"
    if criterion["type"] == "checklist":
        input_type = "checkbox"
    return {
        "id": criterion["id"],
        "number": number,
        "title": criterion["title"],
        "description": criterion["description"],
        "input_name": f"criterion-{criterion['id']}",
        "input_type": input_type,
        "is_bonus": criterion["type"] == "checklist",
        "missing": criterion["title"] in missing,
        "options": _option_rows(criterion, selected, readonly),
    }


def evaluation_form(
    criteria: list[dict],
    selected: dict | None = None,
    missing=(),
    readonly: bool = False,
) -> dict:
    """Rows numbered in authored order, plus the total."""
    selected = selected or {}
    criteria = normalize_stored_criteria(criteria)
    rows = [
        _criterion_row(number, criterion, selected, missing, readonly)
        for number, criterion in enumerate(criteria, start=1)
    ]
    return {
        "rows": rows,
        "total": review_total(criteria, selected),
        "missing_titles": list(missing),
        "readonly": readonly,
    }


def _feedback_field(review) -> str:
    if hasattr(review, "feedback"):
        return "feedback"
    return "note_to_peer"


def _extract_feedback(data) -> str:
    if "feedback" in data:
        return str(data.get("feedback") or "").strip()
    return str(data.get("note_to_peer") or "").strip()


def save_draft(review, criteria: list[dict], data) -> bool:
    """Autosave the posted answers as a draft; True when they were stored."""
    if is_review_complete(review):
        return False
    scores, _total, _missing = score_review(criteria, data)
    feedback_field = _feedback_field(review)
    review.criteria_scores = scores
    setattr(review, feedback_field, _extract_feedback(data))
    review.save(update_fields=["criteria_scores", feedback_field])
    return True


def save_review(review, criteria: list[dict], data) -> tuple[dict, bool]:
    """Submit a posted evaluation; returns ``(form, complete)``."""
    scores, _total, missing = score_review(criteria, data)
    feedback = _extract_feedback(data)
    if missing:
        save_draft(review, criteria, data)
        form = evaluation_form(criteria, scores, missing)
        form["feedback"] = feedback
        return form, False

    feedback_field = _feedback_field(review)
    review.criteria_scores = scores
    setattr(review, feedback_field, feedback)
    update_fields = ["criteria_scores", feedback_field]
    if hasattr(review, "is_complete"):
        review.is_complete = True
        update_fields.append("is_complete")
        if getattr(review, "completed_at", None) is None:
            review.completed_at = timezone.now()
            update_fields.append("completed_at")
    else:
        review.state = "SU"
        update_fields.append("state")
        if getattr(review, "submitted_at", None) is None:
            review.submitted_at = timezone.now()
            update_fields.append("submitted_at")
    review.save(update_fields=update_fields)
    return evaluation_form(criteria, scores), True


def autosave(review, criteria: list[dict], data) -> dict:
    """JSON body for a review autosave request (``peer_review_autosave.js``).

    ``{"saved": True}`` when the draft was stored, ``{"saved": False, "submitted": True}`` once
    the review is already submitted (the script then stops saving).
    """
    if save_draft(review, normalize_stored_criteria(criteria), data):
        return {"saved": True}
    return {"saved": False, "submitted": True}
