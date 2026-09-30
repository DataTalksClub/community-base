"""Refused course-tree homework leaves source and binding unchanged."""

from community_base.content_sync.convert.courses import convert_course_repository
from tests.curriculum.test_mixed_source import mixed_homework_course


def test_duplicate_question_identity_refuses_homework_and_its_binding(tmp_path):
    root = mixed_homework_course(tmp_path)
    homework = root / "01-week-one/04-quiz/homework.yaml"
    cohort = root / "cohorts/2026/cohort.yaml"
    homework.write_text(
        homework.read_text()
        + "  - content_id: 2b3c4d5e-000d-4000-8000-000000000001\n"
        + "    id: first\n    type: free_form\n    prompt: Repeated\n"
        + "    points: 1\n    answer_type: any\n"
    )
    original_homework, original_cohort = homework.read_bytes(), cohort.read_bytes()

    report = convert_course_repository(root)

    assert any("duplicate question identity" in item.message for item in report.refusals)
    assert homework.read_bytes() == original_homework
    assert cohort.read_bytes() == original_cohort
    assert report.verify() == []


def test_explicitly_ignored_course_tree_homework_is_untouched(tmp_path):
    root = mixed_homework_course(tmp_path)
    manifest = root / "content.yaml"
    manifest.write_text(manifest.read_text() + "ignore:\n  - 01-week-one/04-quiz/**\n")
    cohort = root / "cohorts/2026/cohort.yaml"
    cohort.write_text(cohort.read_text().split("homework:\n")[0])
    quiz = root / "01-week-one/04-quiz"
    homework = quiz / "homework.yaml"
    homework.write_text("schema_version: 2\n" + homework.read_text())
    before = {path.name: path.read_bytes() for path in quiz.iterdir()}
    course = root / "course.yaml"
    course.write_text("schema_version: 2\n" + course.read_text())

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert {path.name: path.read_bytes() for path in quiz.iterdir()} == before
    for change in report.changes:
        if change.path.startswith("01-week-one/04-quiz/"):
            assert change.action == "unchanged"
    assert "schema_version" not in course.read_text()
    assert report.verify() == []
