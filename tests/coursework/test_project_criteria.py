"""Tests for structured YAML project evaluation criteria."""

from types import SimpleNamespace

import pytest
from django.http import QueryDict

from community_base.coursework.project_criteria import (
    CriteriaError,
    criteria_summary,
    max_points,
    parse_criteria,
    points_label,
    score_review,
    scores_complete,
    settle_completion,
    split_criteria,
    totals_label,
)

SAMPLE_RAW = [
    {
        "id": "problem-statement",
        "title": "Problem statement",
        "description": "Is the problem clearly defined?",
        "type": "scale",
        "options": [
            {"points": 0, "text": "Not clear"},
            {"points": 1, "text": "Somewhat clear"},
            {"points": 2, "text": "Very clear"},
        ],
    },
    {
        "id": "bonus-tests",
        "title": "Tests",
        "type": "checklist",
        "options": [
            {"points": 1, "text": "Unit tests"},
            {"points": 2, "text": "Integration tests"},
        ],
    },
]


def test_parse_criteria_normalizes_valid_input():
    parsed = parse_criteria(SAMPLE_RAW, "course.yaml")
    assert len(parsed) == 2
    assert parsed[0]["id"] == "problem-statement"
    assert parsed[0]["type"] == "scale"
    assert parsed[1]["description"] == ""
    assert parse_criteria(None, "course.yaml") == []


@pytest.mark.parametrize(
    "bad_raw,match",
    [
        ("not-a-list", "must be a list"),
        (["not-a-dict"], "must be a mapping"),
        (
            [{"id": "Bad_ID", "title": "T", "options": [{"points": 1, "text": "x"}]}],
            "lowercase slug",
        ),
        (
            [
                {"id": "dup", "title": "A", "options": [{"points": 1, "text": "x"}]},
                {"id": "dup", "title": "B", "options": [{"points": 1, "text": "y"}]},
            ],
            "duplicate criterion id",
        ),
        ([{"id": "a", "title": " ", "options": [{"points": 1, "text": "x"}]}], "requires a title"),
        (
            [{"id": "a", "title": "A", "type": "unknown", "options": [{"points": 1, "text": "x"}]}],
            "type must be one of",
        ),
        ([{"id": "a", "title": "A", "options": []}], "requires options"),
        (
            [{"id": "a", "title": "A", "options": [{"points": True, "text": "x"}]}],
            "non-negative integer",
        ),
        (
            [{"id": "a", "title": "A", "options": [{"points": -1, "text": "x"}]}],
            "non-negative integer",
        ),
        ([{"id": "a", "title": "A", "options": [{"points": 1, "text": ""}]}], "requires text"),
    ],
)
def test_parse_criteria_rejects_invalid_input(bad_raw, match):
    with pytest.raises(CriteriaError, match=match):
        parse_criteria(bad_raw, "course.yaml")


def test_summary_and_labels():
    criteria = parse_criteria(SAMPLE_RAW, "course.yaml")
    core, bonus = split_criteria(criteria)
    assert len(core) == 1
    assert len(bonus) == 1
    assert max_points(core[0]) == 2
    assert max_points(bonus[0]) == 3
    assert points_label(1) == "1 point"
    assert points_label(2) == "2 points"
    assert totals_label(18, 0) == "up to 18 points"
    assert totals_label(18, 17) == "up to 18 points, plus up to 17 bonus points"

    summary = criteria_summary(criteria)
    assert summary["core_max"] == 2
    assert summary["bonus_max"] == 3
    assert summary["totals_label"] == "up to 2 points, plus up to 3 bonus points"


def test_score_review_and_settle_completion():
    criteria = parse_criteria(SAMPLE_RAW, "course.yaml")
    post = QueryDict(
        "criterion-problem-statement=2&criterion-bonus-tests=0&criterion-bonus-tests=1"
    )
    scores, total, missing = score_review(criteria, post)
    assert scores == {"problem-statement": 2, "bonus-tests": [0, 1]}
    assert total == 5
    assert missing == []
    assert scores_complete(criteria, scores) is True

    incomplete_post = QueryDict("criterion-bonus-tests=0")
    scores2, total2, missing2 = score_review(criteria, incomplete_post)
    assert missing2 == ["Problem statement"]
    assert total2 == 1
    assert scores_complete(criteria, scores2) is False

    pkg_review = SimpleNamespace(state="SU", criteria_scores={})
    aisl_review = SimpleNamespace(is_complete=True, criteria_scores={"problem-statement": 1})
    settle_completion([pkg_review, aisl_review], criteria)
    assert pkg_review.state == "TR"
    assert aisl_review.is_complete is True
