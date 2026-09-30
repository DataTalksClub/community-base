"""Authored module slugs remain exact through cohort binding conversion."""

from community_base.content_sync.convert.courses import convert_course_repository
from community_base.coursework.manifests import read_cohort_homework
from community_base.curriculum.parsers import parse_course_repository, read_courses
from tests.curriculum.test_mixed_source import mixed_homework_course


def _binding_identity(root):
    parsed = parse_course_repository(root)
    result = read_courses(root)
    assignment = read_cohort_homework(result, result.collections[0], parsed)[0]
    return parsed.course.modules[0].slug, assignment.module_slug, assignment.unit_content_id


def test_exact_authored_prefixed_slug_survives_unit_binding(tmp_path):
    root = mixed_homework_course(tmp_path)
    module = root / "01-week-one/module.yaml"
    module.write_text(module.read_text() + "slug: 01-persistent\n")
    cohort = root / "cohorts/2026/cohort.yaml"
    cohort.write_text(cohort.read_text().replace("week-one", "01-persistent"))
    before = _binding_identity(root)

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert _binding_identity(root) == before


def _two_invalid_cohorts(root):
    first = root / "cohorts/2026/cohort.yaml"
    first.write_text(
        "schema_version: 2\n"
        + first.read_text().replace(
            "2b3c4d5e-000c-4000-8000-000000000001", "ffffffff-000c-4000-8000-000000000001"
        )
    )
    second = root / "cohorts/2027/cohort.yaml"
    second.parent.mkdir()
    second.write_text(
        first.read_text()
        .replace("2b3c4d5e-000a-4000-8000-000000000001", "2b3c4d5e-000a-4000-8000-000000000002")
        .replace("2026", "2027")
    )
    return {path: path.read_bytes() for path in (first, second)}


def test_each_invalid_cohort_binding_is_refused_without_partial_rewrite(tmp_path):
    root = mixed_homework_course(tmp_path)
    before = _two_invalid_cohorts(root)
    course = root / "course.yaml"
    course.write_text("schema_version: 2\n" + course.read_text())

    report = convert_course_repository(root)

    invalid = {
        "cohorts/2026/cohort.yaml",
        "cohorts/2027/cohort.yaml",
    }
    assert {item.path for item in report.refusals} == invalid
    assert all(path.read_bytes() == original for path, original in before.items())
    for change in report.changes:
        if change.path in invalid:
            assert change.action == "refused"
    assert "schema_version" not in course.read_text()
    assert report.verify() == []
