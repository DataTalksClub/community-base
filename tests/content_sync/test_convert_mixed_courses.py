"""Semantic conversion regressions for mixed course repositories."""

import shutil

import pytest
import yaml

from community_base.content_sync.convert.courses import convert_course_repository
from community_base.coursework.manifests import read_cohort_homework
from community_base.curriculum.parsers import parse_course_repository, read_courses
from tests.content_sync.course_conversion_signatures import course_signature
from tests.content_sync.test_convert_courses import MODULE, UNIT, repository
from tests.curriculum.test_mixed_source import mixed_homework_course
from tests.curriculum.utils import DTC_REPO


def _decorate_mixed(root):
    module = root / "01-week-one/module.yaml"
    module.write_text(module.read_text() + "syllabus_section: Foundations\nis_bonus: true\n")
    (root / "01-week-one/README.md").write_text("Week introduction.\n")
    assets = root / "01-week-one/images"
    assets.mkdir()
    (assets / "chart.svg").write_text("<svg></svg>\n")
    quiz = root / "01-week-one/04-quiz/homework.yaml"
    quiz.write_text(
        quiz.read_text()
        + "  - content_id: 2b3c4d5e-000e-4000-8000-000000000001\n"
        + "    id: second\n    type: multiple_choice\n    prompt: Pick first\n"
        + "    points: 3\n    step_label: Second step\n"
        + "    options:\n      - {id: x, label: X}\n      - {id: y, label: Y}\n"
        + "    correct: '1'\n"
    )


def _file_bytes(root):
    found = {}
    for path in root.rglob("*"):
        if path.is_file():
            found[path.relative_to(root)] = path.read_bytes()
    return found


def test_canonical_mixed_tree_and_yaml_homework_keep_parsed_semantics(tmp_path):
    root = mixed_homework_course(tmp_path)
    _decorate_mixed(root)
    assets = root / "01-week-one/images"
    before = course_signature(root)
    assert [row[3] for row in before[0][:4]] == [
        "week-one",
        "topic-a",
        "section-overview",
        "direct",
    ]
    assert len(parse_course_repository(root).course.modules[0].children[0].units) == 1
    original = (root / "01-week-one/04-quiz/homework.md").read_bytes()

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert course_signature(root) == before
    assert (assets / "chart.svg").read_text() == "<svg></svg>\n"
    assert (root / "01-week-one/04-quiz/homework.md").read_bytes() == original
    assert not any(
        "01-week-one/04-quiz/**" in pattern
        for pattern in yaml.safe_load((root / "content.yaml").read_text()).get("ignore", [])
    )
    assert convert_course_repository(root).converted == 0


def test_legacy_unit_list_order_overrides_filename_order(tmp_path):
    manifest = MODULE.replace("01-intro.md", "03-later.md")
    manifest += (
        "  - content_id: 9a2b3c4d-0007-4000-8000-000000000001\n"
        "    title: Earlier filename\n"
        "    path: 01-earlier.md\n"
    )
    root = repository(
        tmp_path,
        **{
            "01-agentic-rag/module.yaml": manifest,
            "01-agentic-rag/03-later.md": UNIT,
            "01-agentic-rag/01-earlier.md": "---\n---\nEarlier body.\n",
        },
    )
    (root / "01-agentic-rag/01-intro.md").unlink()

    report = convert_course_repository(root)

    assert report.ok, report.render()
    units = parse_course_repository(root).course.modules[0].units
    assert [unit.title for unit in units] == ["Introduction", "Earlier filename"]
    assert [unit.sort_order for unit in units] == [1, 2]


@pytest.mark.parametrize("name", ["direct.md", "01-direct.md"])
def test_ambiguous_mixed_order_refuses_affected_files_but_applies_course(tmp_path, name):
    root = mixed_homework_course(tmp_path)
    week = root / "01-week-one"
    (week / "02-direct.md").rename(week / name)
    course = root / "course.yaml"
    course.write_text("schema_version: 2\n" + course.read_text())
    before = _file_bytes(week)

    report = convert_course_repository(root)

    assert any(name in item.path or name in item.message for item in report.refusals)
    assert _file_bytes(week) == before
    assert "schema_version" not in course.read_text()
    assert report.verify() == []


def test_unit_binding_with_stored_module_slug_and_override_survives(tmp_path):
    root = mixed_homework_course(tmp_path)
    week = root / "01-week-one/module.yaml"
    week.write_text(week.read_text() + "slug: foundations\n")
    cohort = root / "cohorts/2026/cohort.yaml"
    cohort.write_text(
        cohort.read_text()
        .replace("week-one", "foundations")
        .replace(
            "    unit: 2b3c4d5e-000c-4000-8000-000000000001\n",
            "    unit: 2b3c4d5e-000c-4000-8000-000000000001\n    initial_state: open\n",
        )
    )
    before = course_signature(root)

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert course_signature(root) == before
    parsed = parse_course_repository(root)
    result = read_courses(root)
    assignment = read_cohort_homework(result, result.collections[0], parsed)[0]
    assert assignment.initial_state == "open"


def test_invalid_unit_binding_refuses_cohort_without_touching_it(tmp_path):
    root = mixed_homework_course(tmp_path)
    cohort = root / "cohorts/2026/cohort.yaml"
    cohort.write_text(
        cohort.read_text().replace(
            "2b3c4d5e-000c-4000-8000-000000000001", "2b3c4d5e-ffff-4000-8000-000000000001"
        )
    )
    before = cohort.read_bytes()

    report = convert_course_repository(root)

    assert any("/homework/0/unit" in item.message for item in report.refusals)
    assert cohort.read_bytes() == before
    assert report.verify() == []


def test_source_manifest_binding_and_explicit_ignore_keep_their_meaning(tmp_path):
    root = tmp_path / "course"
    shutil.copytree(DTC_REPO, root)
    cohort = root / "cohorts/2026/cohort.yaml"
    cohort.write_text(
        cohort.read_text().replace(
            "source: homework/core/homework.yaml",
            "source: cohorts/2026/homework/core/homework.yaml",
        )
    )
    manifest = root / "content.yaml"
    manifest.write_text(manifest.read_text() + "ignore:\n  - notes/**\n")
    notes = root / "notes"
    notes.mkdir()
    (notes / "draft.md").write_text("Unpublished notes.\n")
    homework = root / "cohorts/2026/homework/core/homework.yaml"
    homework.write_text("schema_version: 2\n" + homework.read_text())

    report = convert_course_repository(root)

    assert report.ok, report.render()
    parsed = parse_course_repository(root)
    result = read_courses(root)
    assignment = read_cohort_homework(result, result.collections[0], parsed)[0]
    assert assignment.source_path == "cohorts/2026/homework/core/homework.yaml"
    assert assignment.unit_content_id == "9a2b3c4d-0003-4000-8000-000000000002"
    assert [item.stable_id for item in assignment.questions] == ["q1", "q2"]
    assert yaml.safe_load(manifest.read_text())["ignore"] == ["notes/**"]
    assert (notes / "draft.md").read_text() == "Unpublished notes.\n"


def test_course_tree_homework_version_is_removed_without_losing_authored_values(tmp_path):
    root = mixed_homework_course(tmp_path)
    homework = root / "01-week-one/04-quiz/homework.yaml"
    original = yaml.safe_load(homework.read_text())
    homework.write_text("schema_version: 2\n" + homework.read_text())

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert yaml.safe_load(homework.read_text()) == original
    parsed = parse_course_repository(root)
    result = read_courses(root)
    assignment = read_cohort_homework(result, result.collections[0], parsed)[0]
    assert assignment.questions[0].correct == "2"
    assert assignment.questions[0].options[1].id == "b"


def test_conflicting_legacy_list_and_explicit_order_refuses_only_module(tmp_path):
    first = MODULE.replace("    path: 01-intro.md", "    path: 01-intro.md\n    sort_order: 2")
    first += (
        "  - content_id: 9a2b3c4d-0007-4000-8000-000000000001\n"
        "    title: Second\n"
        "    path: 02-second.md\n"
        "    sort_order: 1\n"
    )
    root = repository(
        tmp_path,
        **{
            "01-agentic-rag/module.yaml": first,
            "01-agentic-rag/02-second.md": "---\n---\nSecond body.\n",
        },
    )
    module = root / "01-agentic-rag/module.yaml"
    original = module.read_bytes()

    report = convert_course_repository(root)

    assert any("contradictory authored list" in item.message for item in report.refusals)
    assert module.read_bytes() == original
    assert report.verify() == []


def test_mixed_dry_run_reports_proposals_and_writes_nothing(tmp_path):
    root = mixed_homework_course(tmp_path)
    course = root / "course.yaml"
    course.write_text("schema_version: 2\n" + course.read_text())
    before = _file_bytes(root)

    report = convert_course_repository(root, apply=False)

    assert report.ok, report.render()
    assert report.applied is False
    assert "proposed changes (dry run; no files written)" in report.render()
    assert report.converted > 0
    assert _file_bytes(root) == before
