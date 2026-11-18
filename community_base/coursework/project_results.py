"""Project scores computed from peer reviews with YAML criteria."""

import math
import statistics
from dataclasses import dataclass

from community_base.coursework.project_criteria import (
    is_review_complete,
    max_points,
    points_label,
    project_evaluation_criteria,
)


@dataclass(frozen=True)
class CriterionResult:
    id: str
    title: str
    type: str
    score: int
    options: tuple
    max_points: int = 0
    chosen_text: str = ""

    @property
    def is_bonus(self) -> bool:
        return self.type == "checklist"

    @property
    def bonus_marker(self) -> bool:
        return self.is_bonus and "bonus" not in self.title.lower()


@dataclass(frozen=True)
class ProjectResult:
    total: int
    criteria: tuple
    review_count: int
    passing_score: int
    passed: bool | None


def _scale_index(criterion: dict, value) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value < len(criterion["options"]):
            return value
    return None


def _checked_indexes(criterion: dict, value) -> list[int]:
    if not isinstance(value, list):
        return []
    picked = []
    for index in value:
        if _scale_index(criterion, index) is not None:
            picked.append(index)
    return picked


def chosen_indexes(criterion: dict, criteria_scores: dict) -> list[int]:
    """Option indexes a review picked for one criterion (blank -> [])."""
    value = criteria_scores.get(criterion["id"])
    if criterion["type"] == "checklist":
        return _checked_indexes(criterion, value)
    index = _scale_index(criterion, value)
    if index is None:
        return []
    return [index]


def criterion_points(criterion: dict, criteria_scores: dict) -> int:
    """Points one review gives one criterion; an unanswered one scores 0."""
    options = criterion["options"]
    return sum(options[i]["points"] for i in chosen_indexes(criterion, criteria_scores))


def review_total(criteria: list[dict], criteria_scores: dict) -> int:
    return sum(criterion_points(c, criteria_scores) for c in criteria)


def _review_project(review):
    submission = getattr(review, "submission", None) or getattr(
        review, "submission_under_evaluation", None
    )
    if submission is None:
        return None
    return getattr(submission, "project", None) or getattr(submission, "course_project", None)


def review_points(review) -> int | None:
    """Total points of ONE review for its project's criteria, else None."""
    project = _review_project(review)
    criteria = project_evaluation_criteria(project)
    if not criteria:
        return None
    if not is_review_complete(review):
        return None
    return review_total(criteria, review.criteria_scores or {})


def default_criterion_score(criterion: dict) -> int:
    """No-review fallback for one criterion."""
    points = [opt["points"] for opt in criterion["options"]]
    if criterion["type"] == "checklist":
        return math.ceil(sum(points) / 2)
    return math.ceil(statistics.median(points))


def _votes(criterion: dict, score_dicts: list[dict]) -> tuple[dict, ...]:
    counts = [0] * len(criterion["options"])
    for scores in score_dicts:
        for index in chosen_indexes(criterion, scores):
            counts[index] += 1
    options = []
    for index, option in enumerate(criterion["options"]):
        label = f"{option['text']} ({points_label(option['points'])})"
        options.append({**option, "label": label, "votes": counts[index]})
    return tuple(options)


def _chosen(
    criterion: dict, options: tuple[dict, ...], score: int, reviewers: int
) -> tuple[int, ...]:
    if not reviewers:
        return ()
    if criterion["type"] == "checklist":
        picked = tuple(i for i, opt in enumerate(options) if opt["votes"] * 2 > reviewers)
        if sum(options[i]["points"] for i in picked) == score:
            return picked
        return ()
    matches = [i for i, opt in enumerate(options) if opt["points"] == score]
    if not matches:
        return ()
    return (max(matches, key=lambda i: options[i]["votes"]),)


def _criterion_result(criterion: dict, score_dicts: list[dict]) -> CriterionResult:
    if score_dicts:
        points = [criterion_points(criterion, s) for s in score_dicts]
        score = math.ceil(statistics.median(points))
    else:
        score = default_criterion_score(criterion)
    options = _votes(criterion, score_dicts)
    chosen = _chosen(criterion, options, score, len(score_dicts))
    options = tuple({**opt, "chosen": i in chosen} for i, opt in enumerate(options))
    return CriterionResult(
        id=criterion["id"],
        title=criterion["title"],
        type=criterion["type"],
        score=score,
        options=options,
        max_points=max_points(criterion),
        chosen_text="; ".join(options[i]["text"] for i in chosen),
    )


def project_result(
    criteria: list[dict],
    reviews,
    passing_score: int = 0,
    reviewed_enough: bool = True,
) -> ProjectResult | None:
    """Score one submission from its complete reviews; None without criteria."""
    if not criteria:
        return None
    score_dicts = [review.criteria_scores or {} for review in reviews]
    rows = tuple(_criterion_result(c, score_dicts) for c in criteria)
    total = sum(row.score for row in rows)
    passed = None
    if passing_score > 0:
        passed = total >= passing_score and reviewed_enough
    return ProjectResult(
        total=total,
        criteria=rows,
        review_count=len(score_dicts),
        passing_score=passing_score,
        passed=passed,
    )
