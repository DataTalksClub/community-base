"""Tests for project scoring from YAML criteria peer reviews."""

from types import SimpleNamespace

from community_base.coursework.project_criteria import parse_criteria
from community_base.coursework.project_results import (
    default_criterion_score,
    project_result,
    review_points,
    review_total,
)

CRITERIA = parse_criteria(
    [
        {
            "id": "clarity",
            "title": "Clarity",
            "type": "scale",
            "options": [
                {"points": 0, "text": "No"},
                {"points": 1, "text": "Partly"},
                {"points": 2, "text": "Yes"},
            ],
        },
        {
            "id": "bonus",
            "title": "Extra work",
            "type": "checklist",
            "options": [
                {"points": 1, "text": "CI"},
                {"points": 2, "text": "Docker"},
            ],
        },
    ],
    "course.yaml",
)


def test_project_result_with_reviews_and_passing_score():
    reviews = [
        SimpleNamespace(criteria_scores={"clarity": 2, "bonus": [0, 1]}),
        SimpleNamespace(criteria_scores={"clarity": 1, "bonus": [0]}),
        SimpleNamespace(criteria_scores={"clarity": 2, "bonus": [0, 1]}),
    ]
    res = project_result(CRITERIA, reviews, passing_score=4, reviewed_enough=True)
    assert res is not None
    assert res.total == 5  # clarity median=2, bonus median([3, 1, 3])=3
    assert res.passed is True
    assert res.review_count == 3
    assert res.criteria[0].chosen_text == "Yes"
    assert res.criteria[1].bonus_marker is True

    not_enough = project_result(CRITERIA, reviews, passing_score=4, reviewed_enough=False)
    assert not_enough.passed is False


def test_project_result_no_reviews_uses_default_score():
    assert default_criterion_score(CRITERIA[0]) == 1
    assert default_criterion_score(CRITERIA[1]) == 2
    res = project_result(CRITERIA, [])
    assert res.total == 3
    assert res.passed is None
    assert project_result([], []) is None


def test_review_points_works_with_package_and_site_shapes():
    project = SimpleNamespace(evaluation_criteria=CRITERIA)
    sub = SimpleNamespace(project=project)
    complete = SimpleNamespace(
        state="SU", submission_under_evaluation=sub, criteria_scores={"clarity": 2}
    )
    incomplete = SimpleNamespace(
        state="TR", submission_under_evaluation=sub, criteria_scores={"clarity": 2}
    )
    assert review_total(CRITERIA, {"clarity": 2, "bonus": [1]}) == 4
    assert review_points(complete) == 2
    assert review_points(incomplete) is None
