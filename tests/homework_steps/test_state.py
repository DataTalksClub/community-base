from datetime import UTC, datetime

import pytest

from community_base.homework_steps.state import calculate_homework_state
from community_base.homework_steps.types import (
    AcceptedSubmission,
    Assignment,
    FinalField,
    Option,
    Question,
)


def _assignment(*, availability="open", accepted_submission=None):
    return Assignment(
        key="course:cohort:homework",
        title="Homework",
        questions=(
            Question("choice", "Choose", "choice", (Option("a", "Alpha"), Option("b", "Beta"))),
            Question("checks", "Select", "checkbox", (Option("x", "X"), Option("y", "Y"))),
            Question("text", "Explain", "long_text"),
        ),
        final_fields=(FinalField("link", "Project link", "url"),),
        availability=availability,
        accepted_submission=accepted_submission,
    )


@pytest.mark.parametrize(
    ("availability", "accepted", "draft_answers", "draft_exists", "expected"),
    [
        ("open", None, {}, False, "not_submitted"),
        ("open", None, {"text": "Saved work"}, True, "draft"),
        ("open", AcceptedSubmission(answers={"choice": "a"}), {"choice": "a"}, True, "submitted"),
        (
            "open",
            AcceptedSubmission(answers={"choice": "a"}),
            {"choice": "b"},
            True,
            "unsubmitted_changes",
        ),
        ("closed", None, {"text": "Saved work"}, True, "closed_not_submitted"),
        ("scored", None, {"text": "Saved work"}, True, "closed_not_submitted"),
        (
            "closed",
            AcceptedSubmission(answers={"choice": "a"}),
            {"choice": "a"},
            True,
            "submitted",
        ),
        (
            "scored",
            AcceptedSubmission(answers={"choice": "a"}),
            {"choice": "a"},
            True,
            "scored",
        ),
    ],
)
def test_six_state_mapping(availability, accepted, draft_answers, draft_exists, expected):
    result = calculate_homework_state(
        _assignment(availability=availability, accepted_submission=accepted),
        draft_answers=draft_answers,
        draft_exists=draft_exists,
    )

    assert result.value == expected


def test_seeded_draft_matches_complete_accepted_snapshot_including_blank_values():
    accepted = AcceptedSubmission(
        answers={"choice": "a", "checks": ["y", "x"], "text": ""},
        final_fields={"link": ""},
        submitted_at=datetime(2026, 9, 26, 10, 30, tzinfo=UTC),
    )
    result = calculate_homework_state(
        _assignment(accepted_submission=accepted),
        draft_answers={"choice": "a", "checks": ["x", "y"]},
        draft_final_fields={},
        draft_exists=True,
    )

    assert result.value == "submitted"
    assert result.has_pending_changes is False
    assert result.submitted_at == accepted.submitted_at


def test_closed_changed_draft_keeps_submitted_status_but_marks_changes_separately():
    accepted = AcceptedSubmission(answers={"choice": "a"})
    result = calculate_homework_state(
        _assignment(availability="closed", accepted_submission=accepted),
        draft_answers={"choice": "b"},
        draft_exists=True,
    )

    assert result.value == "submitted"
    assert result.has_pending_changes is True


def test_changed_final_field_counts_as_an_unsubmitted_change():
    accepted = AcceptedSubmission(final_fields={"link": "https://accepted.example"})
    result = calculate_homework_state(
        _assignment(accepted_submission=accepted),
        draft_final_fields={"link": "https://draft.example"},
        draft_exists=True,
    )

    assert result.value == "unsubmitted_changes"
    assert result.has_pending_changes is True


def test_scored_without_accepted_submission_never_claims_scored():
    result = calculate_homework_state(
        _assignment(availability="scored"),
        draft_answers={"text": "Work not submitted"},
        draft_exists=True,
    )

    assert result.value == "closed_not_submitted"
    assert result.label == "Closed — not submitted"


def test_unknown_availability_is_rejected():
    with pytest.raises(ValueError, match="availability"):
        calculate_homework_state(_assignment(availability="hidden"))
