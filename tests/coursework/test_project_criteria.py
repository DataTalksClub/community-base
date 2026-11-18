"""Tests for structured YAML project evaluation criteria."""

from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.http import QueryDict

from community_base.coursework.models import (
    PeerReview,
    ProjectCriteriaSetAssignment,
    ProjectSubmission,
    ReviewCriteriaSet,
)
from community_base.coursework.project_criteria import (
    CriteriaError,
    MissingProjectCriteriaError,
    assign_project_criteria_set,
    criteria_summary,
    get_project_criteria_set,
    max_points,
    parse_criteria,
    parse_criteria_set,
    points_label,
    project_evaluation_criteria,
    require_criteria,
    require_project_criteria,
    resolve_project_criteria,
    score_review,
    scores_complete,
    settle_completion,
    split_criteria,
    totals_label,
    validate_project_criteria_references,
)
from community_base.coursework.project_results import review_points
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import make_project

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


def test_parse_criteria_set_and_require_criteria():
    with pytest.raises(CriteriaError, match="at least one criterion"):
        require_criteria([], "rubric.yaml")
    with pytest.raises(CriteriaError, match="at least one criterion"):
        require_criteria(None, "rubric.yaml")

    parsed = parse_criteria_set(
        {
            "slug": "capstone-rubric",
            "title": "Capstone Rubric",
            "description": "Shared capstone evaluation criteria",
            "criteria": SAMPLE_RAW,
        },
        "criteria/capstone-rubric.yaml",
    )
    assert parsed["slug"] == "capstone-rubric"
    assert parsed["title"] == "Capstone Rubric"
    assert len(parsed["criteria"]) == 2

    with pytest.raises(CriteriaError, match="requires a title"):
        parse_criteria_set({"slug": "bad", "criteria": SAMPLE_RAW}, "bad.yaml")


def test_resolve_and_validate_project_criteria_references():
    rubric_a = parse_criteria_set(
        {"slug": "rubric-a", "title": "Rubric A", "criteria": SAMPLE_RAW[:1]},
        "rubric-a.yaml",
    )
    rubric_b = parse_criteria_set(
        {"slug": "rubric-b", "title": "Rubric B", "criteria": SAMPLE_RAW},
        "rubric-b.yaml",
    )
    sets = {"rubric-a": rubric_a, "rubric-b": rubric_b}

    # Two projects sharing the same criteria set and a third using a different one.
    resolved = validate_project_criteria_references(
        [
            {"slug": "project-1", "criteria": "rubric-a"},
            {"slug": "project-2", "criteria": "review_criteria:rubric-a"},
            {"slug": "project-3", "criteria": "rubric-b"},
        ],
        sets,
        where="course",
    )
    assert len(resolved["project-1"]) == 1
    assert resolved["project-1"] == resolved["project-2"]
    assert len(resolved["project-3"]) == 2

    with pytest.raises(MissingProjectCriteriaError, match="must reference a review criteria set"):
        resolve_project_criteria("", sets, where="project-1")

    with pytest.raises(MissingProjectCriteriaError, match="unknown review criteria set"):
        resolve_project_criteria("missing-rubric", sets, where="project-1")

    # Object-style project definitions with `criteria` / `criteria_set` attributes also resolve.
    obj_resolved = validate_project_criteria_references(
        [
            SimpleNamespace(slug="obj-1", criteria="rubric-a"),
            SimpleNamespace(slug="obj-2", criteria_set="review_criteria:rubric-b"),
        ],
        sets,
        where="course",
    )
    assert obj_resolved["obj-1"] == rubric_a["criteria"]
    assert obj_resolved["obj-2"] == rubric_b["criteria"]


@pytest.mark.django_db
def test_reusable_criteria_sets_for_projects_in_same_course():
    cohort = coursework_cohort()
    project_one = make_project(cohort, slug="project-one", title="Project One")
    project_two = make_project(cohort, slug="project-two", title="Project Two")
    project_three = make_project(cohort, slug="project-three", title="Project Three")

    rubric_a = ReviewCriteriaSet.objects.create(
        slug="shared-rubric",
        title="Shared Rubric",
        criteria=parse_criteria(SAMPLE_RAW[:1], "shared.yaml"),
    )
    rubric_b = ReviewCriteriaSet.objects.create(
        slug="capstone-rubric",
        title="Capstone Rubric",
        criteria=parse_criteria(SAMPLE_RAW, "capstone.yaml"),
    )

    # Project 1 and Project 2 in the same cohort/course share rubric_a; Project 3 uses rubric_b.
    assign_project_criteria_set(project_one, "shared-rubric")
    assign_project_criteria_set(project_two, rubric_a)
    assign_project_criteria_set(project_three, "review_criteria:capstone-rubric")

    assert project_one.criteria_set == rubric_a
    assert project_two.criteria_set == rubric_a
    assert get_project_criteria_set(project_three) == rubric_b
    assert len(require_project_criteria(project_one)) == 1
    assert len(project_evaluation_criteria(project_three)) == 2

    # Protected against deletion while assigned.
    with pytest.raises(ProtectedError):
        rubric_a.delete()

    # Unassigned project triggers guard.
    unassigned = make_project(cohort, slug="unassigned", title="Unassigned")
    assert unassigned.criteria_set is None
    with pytest.raises(MissingProjectCriteriaError, match="no review criteria set"):
        require_project_criteria(unassigned)

    with pytest.raises(MissingProjectCriteriaError, match="unknown review criteria set"):
        assign_project_criteria_set(unassigned, "does-not-exist")

    # Empty criteria rejected on model clean.
    bad_set = ReviewCriteriaSet(slug="empty-set", title="Empty", criteria=[])
    with pytest.raises(ValidationError, match="at least one criterion"):
        bad_set.full_clean()

    # review_points integrates with ProjectCriteriaSetAssignment.
    _u1, e1 = enrollment_for(cohort, email="u1@example.com")
    _u2, e2 = enrollment_for(cohort, email="u2@example.com")
    sub1 = ProjectSubmission.objects.create(
        project=project_one, student=e1.user, enrollment=e1, github_link="https://github.com/a/b"
    )
    sub2 = ProjectSubmission.objects.create(
        project=project_one, student=e2.user, enrollment=e2, github_link="https://github.com/c/d"
    )
    review = PeerReview(
        submission_under_evaluation=sub1,
        reviewer=sub2,
        note_to_peer="Nice",
        state="SU",
    )
    review.criteria_scores = {"problem-statement": 2}
    assert review_points(review) == 2

    assert ProjectCriteriaSetAssignment.objects.count() == 3

    # Reassigning a project updates its single assignment rather than creating a duplicate.
    assign_project_criteria_set(project_one, rubric_b)
    assert get_project_criteria_set(project_one) == rubric_b
    assert len(require_project_criteria(project_one)) == 2
    assert ProjectCriteriaSetAssignment.objects.count() == 3
