"""A host reader resolves project references through the shared course graph."""

import shutil

import pytest

from community_base.content_sync.check import check_repository
from community_base.curriculum.content_sync_parsers import CourseParser
from community_base.curriculum.models import Course, CurriculumImportRun, Module, Unit
from community_base.curriculum.parsers import parse_course_repository
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.utils import DTC_NESTED, checkout, make_source

SITE_READER = "tests.content_sync.site_project_module_reader"


def project_course(tmp_path, module_path, *, extra_field=False):
    root = tmp_path / "project-course"
    shutil.copytree(DTC_NESTED, root)
    course = root / "course.yaml"
    lines = [
        "extra:",
        "  project_module_refs:",
        "    - id: cohort-2026/project-a",
        f"      module_path: {module_path}",
    ]
    if extra_field:
        lines.append("      unexplained: value")
    course.write_text(course.read_text() + "\n" + "\n".join(lines) + "\n")
    return root


def test_registered_reader_resolves_nested_project_module_in_check_and_parse(tmp_path):
    root = project_course(tmp_path, "01-week-one/01-topic-a")

    assert check_repository(root, kind_modules=[SITE_READER]) == []
    (binding,) = parse_course_repository(root).course.project_modules
    assert binding.project_id == "cohort-2026/project-a"
    assert binding.module_path == "01-week-one/01-topic-a"
    assert binding.module_source_path == "01-week-one/01-topic-a/module.yaml"
    assert binding.module_content_id == "2b3c4d5e-0003-4000-8000-000000000001"


@pytest.mark.django_db
@pytest.mark.parametrize("module_path", ["01-missing", "../01-week-one"])
def test_bad_project_module_path_fails_check_and_sync_before_domain_writes(tmp_path, module_path):
    root = project_course(tmp_path, module_path)
    diagnostics = check_repository(root, kind_modules=[SITE_READER])
    assert len(diagnostics) == 1
    assert diagnostics[0].path == "course.yaml"
    assert diagnostics[0].pointer == "/extra/project_module_refs/0/module_path"

    source = make_source()
    parser = CourseParser()
    with checkout(root) as active:
        (item,) = parser.discover(active, source)
        with pytest.raises(CurriculumParseError):
            parser.upsert(item, source, None)
    assert not Course.objects.exists()
    assert not Module.objects.exists()
    assert not Unit.objects.exists()
    assert not CurriculumImportRun.objects.exists()


def test_host_reader_rejects_unreviewed_project_source_field(tmp_path):
    root = project_course(tmp_path, "01-week-one/01-topic-a", extra_field=True)

    diagnostics = check_repository(root, kind_modules=[SITE_READER])
    assert len(diagnostics) == 1
    assert diagnostics[0].path == "course.yaml"
    assert "unknown or missing fields" in diagnostics[0].message


def test_duplicate_project_identity_is_rejected_before_resolution(tmp_path):
    root = project_course(tmp_path, "01-week-one/01-topic-a")
    course = root / "course.yaml"
    course.write_text(
        course.read_text()
        + "    - id: cohort-2026/project-a\n"
        + "      module_path: 01-week-one/03-topic-b\n"
    )

    diagnostics = check_repository(root, kind_modules=[SITE_READER])

    assert len(diagnostics) == 1
    assert diagnostics[0].path == "course.yaml"
    assert "duplicate project identity" in diagnostics[0].message
