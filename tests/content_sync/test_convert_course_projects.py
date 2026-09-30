"""Project-module references survive the one-time course conversion."""

from community_base.content_sync.convert.courses import convert_course_repository
from community_base.curriculum.parsers import parse_course_repository
from community_base.curriculum.project_modules import ProjectModuleReference
from tests.curriculum.test_mixed_source import mixed_homework_course


def test_project_module_reference_keeps_its_nested_target(tmp_path, monkeypatch):
    from community_base.curriculum import project_modules

    root = mixed_homework_course(tmp_path)
    course = root / "course.yaml"
    course.write_text(
        course.read_text()
        + "extra:\n  project_module_refs:\n"
        + "    - {id: project-one, module_path: 01-week-one/01-topic-a}\n"
    )

    def read_projects(result, collection):
        data = result.by_path()["course.yaml"].values["extra"]
        for row in data["project_module_refs"]:
            yield ProjectModuleReference(row["id"], "course.yaml", row["module_path"])

    monkeypatch.setattr(project_modules, "_reader", read_projects)
    before = parse_course_repository(root).course.project_modules
    course.write_text("schema_version: 2\n" + course.read_text())

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert parse_course_repository(root).course.project_modules == before
    assert before[0].module_content_id == "2b3c4d5e-0003-4000-8000-000000000001"
