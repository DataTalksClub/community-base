"""Tests for standalone `review_criteria` content kind, validation, and sync."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from community_base.content_sync.check import check_repository
from community_base.content_sync.kinds import (
    SHAPE_MANIFEST,
    KeySpec,
    KindSpec,
    is_registered,
    kind_order,
    register_kind,
)
from community_base.content_sync.kinds.layouts import FlatLayout
from community_base.content_sync.models import ContentSource
from community_base.coursework.content_sync_parsers import (
    ReviewCriteriaParseError,
    ReviewCriteriaParser,
)
from community_base.coursework.models import ReviewCriteriaSet
from community_base.coursework.project_criteria import assign_project_criteria_set
from tests.coursework.test_models import coursework_cohort
from tests.coursework.test_projects import make_project

CRITERIA_A_YAML = """content_id: 11111111-1111-4111-8111-111111111111
title: Standard Project Rubric
description: Reusable rubric for standard projects
criteria:
  - id: problem-statement
    title: Problem statement
    type: scale
    options:
      - points: 0
        text: Missing
      - points: 2
        text: Clear
"""

CRITERIA_B_YAML = """content_id: 22222222-2222-4222-8222-222222222222
title: Capstone Rubric
criteria:
  - id: architecture
    title: Architecture
    type: scale
    options:
      - points: 0
        text: Poor
      - points: 3
        text: Solid
  - id: bonus-tests
    title: Tests
    type: checklist
    options:
      - points: 1
        text: Unit tests
"""


class LocalCheckout:
    def __init__(self, root: Path, commit_sha: str = "a" * 40):
        self.root = root
        self.commit_sha = commit_sha

    def files(self):
        return sorted(
            path.relative_to(self.root) for path in self.root.rglob("*") if path.is_file()
        )

    def read_text(self, path):
        return (self.root / path).read_text(encoding="utf-8")

    def read_bytes(self, path):
        return (self.root / path).read_bytes()


def _write_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _ensure_test_project_kind():
    if not is_registered("test_project"):
        register_kind(
            "test_project",
            KindSpec(
                name="test_project",
                shape=SHAPE_MANIFEST,
                layout=FlatLayout(part="test_project", suffix=".yaml"),
                keys={
                    "criteria": KeySpec(
                        "reference", reference_kind="review_criteria", required=True
                    ),
                },
            ),
        )


def test_review_criteria_validation_and_per_project_references(tmp_path):
    _ensure_test_project_kind()
    order = kind_order()
    assert order.index("review_criteria") < order.index("test_project")

    repo = _write_repo(
        tmp_path,
        {
            "content.yaml": (
                "schema_version: 1\n"
                "collections:\n"
                "  - kind: review_criteria\n"
                "    path: criteria\n"
                "  - kind: test_project\n"
                "    path: projects\n"
            ),
            "criteria/standard.yaml": CRITERIA_A_YAML,
            "criteria/capstone.yaml": CRITERIA_B_YAML,
            "projects/proj-1.yaml": (
                "content_id: 33333333-3333-4333-8333-333333333333\n"
                "title: Project 1\n"
                "criteria: standard\n"
            ),
            "projects/proj-2.yaml": (
                "content_id: 44444444-4444-4444-8444-444444444444\n"
                "title: Project 2\n"
                "criteria: review_criteria:standard\n"
            ),
            "projects/proj-3.yaml": (
                "content_id: 55555555-5555-4555-8555-555555555555\n"
                "title: Project 3\n"
                "criteria: capstone\n"
            ),
        },
    )
    diagnostics = check_repository(repo)
    errors = [d for d in diagnostics if d.severity == "error"]
    assert errors == [], [d.render() for d in errors]


def test_check_repository_rejects_missing_and_unknown_project_criteria_refs(tmp_path):
    _ensure_test_project_kind()
    repo = _write_repo(
        tmp_path,
        {
            "content.yaml": (
                "schema_version: 1\n"
                "collections:\n"
                "  - kind: review_criteria\n"
                "    path: criteria\n"
                "  - kind: test_project\n"
                "    path: projects\n"
            ),
            "criteria/standard.yaml": CRITERIA_A_YAML,
            "projects/missing-ref.yaml": (
                "content_id: 33333333-3333-4333-8333-333333333333\ntitle: Missing Criteria Ref\n"
            ),
            "projects/unknown-ref.yaml": (
                "content_id: 44444444-4444-4444-8444-444444444444\n"
                "title: Unknown Criteria Ref\n"
                "criteria: nonexistent\n"
            ),
        },
    )
    rendered = "\n".join(d.render() for d in check_repository(repo))
    assert "missing-ref.yaml" in rendered
    assert "unknown-ref.yaml" in rendered
    assert "nonexistent" in rendered


def test_check_repository_rejects_empty_or_invalid_criteria_set(tmp_path):
    repo = _write_repo(
        tmp_path,
        {
            "content.yaml": (
                "schema_version: 1\ncollections:\n  - kind: review_criteria\n    path: criteria\n"
            ),
            "criteria/empty.yaml": (
                "content_id: 11111111-1111-4111-8111-111111111111\n"
                "title: Empty Rubric\n"
                "criteria: []\n"
            ),
        },
    )
    diagnostics = check_repository(repo)
    assert any("at least one criterion" in d.message for d in diagnostics)


@pytest.mark.django_db
def test_review_criteria_parser_sync_upsert_and_soft_delete(tmp_path):
    source = ContentSource.objects.create(
        slug="aisl-content",
        repo_name="AI-Shipping-Labs/content",
        webhook_secret="secret",
    )
    repo = _write_repo(
        tmp_path,
        {
            "content.yaml": (
                "schema_version: 1\ncollections:\n  - kind: review_criteria\n    path: criteria\n"
            ),
            "criteria/standard.yaml": CRITERIA_A_YAML,
            "criteria/capstone.yaml": CRITERIA_B_YAML,
        },
    )

    parser = ReviewCriteriaParser()
    media = SimpleNamespace()
    items = parser.discover(LocalCheckout(repo), source)
    assert len(items) == 2

    actions = [parser.upsert(item, source, media).action for item in items]
    assert actions == ["created", "created"]
    assert ReviewCriteriaSet.objects.count() == 2

    # Second sync with no changes is unchanged.
    items_again = parser.discover(LocalCheckout(repo), source)
    assert [parser.upsert(item, source, media).action for item in items_again] == [
        "unchanged",
        "unchanged",
    ]

    # Bind capstone to a project, then remove both files from git:
    # standard is deleted, capstone is guarded and marked draft instead of crashing.
    cohort = coursework_cohort()
    project = make_project(cohort, slug="proj-1")
    assign_project_criteria_set(project, "capstone")

    (repo / "criteria" / "standard.yaml").unlink()
    (repo / "criteria" / "capstone.yaml").unlink()
    items_after = parser.discover(LocalCheckout(repo), source)
    assert items_after == ()
    affected = parser.soft_delete_missing(set(), source)
    assert affected == 2
    assert not ReviewCriteriaSet.objects.filter(slug="standard").exists()
    capstone = ReviewCriteriaSet.objects.get(slug="capstone")
    assert capstone.status == ReviewCriteriaSet.STATUS_DRAFT

    # Invalid criteria YAML raises ReviewCriteriaParseError on discover.
    (repo / "criteria" / "broken.yaml").write_text(
        "content_id: 99999999-9999-4999-8999-999999999999\ntitle: Broken\ncriteria: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ReviewCriteriaParseError, match="at least one criterion"):
        parser.discover(LocalCheckout(repo), source)
