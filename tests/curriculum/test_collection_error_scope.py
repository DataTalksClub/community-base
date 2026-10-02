"""Collection read errors preserve parser rejection and semantic diagnostics."""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest

from community_base.content_sync.check import check_repository
from community_base.content_sync.documents import Diagnostic
from community_base.curriculum.parsers import (
    check_read,
    course_collections,
    parse_course,
    parse_course_repository,
    read_courses,
)
from community_base.curriculum.source import CurriculumParseError
from community_base.curriculum.source_validation import course_source_diagnostics


def write_document(root, path, title, *, body=None, extra=""):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = f"content_id: {uuid5(NAMESPACE_URL, path)}\ntitle: {title}\n{extra}"
    if body is not None:
        metadata = f"---\n{metadata}---\n{body}\n"
    target.write_text(metadata)


def repository(tmp_path, paths=("courses/alpha", "courses/beta")):
    entries = []
    for path in paths:
        entries.append(f"  - kind: course\n    path: {path or '.'}\n")
        prefix = path
        if prefix:
            prefix += "/"
        write_document(
            tmp_path, f"{prefix}course.yaml", "Course", extra="slug: sample\ndescription: Learn.\n"
        )
        write_document(tmp_path, f"{prefix}01-core/module.yaml", "Core")
        write_document(tmp_path, f"{prefix}01-core/01-lesson.md", "Lesson", body="Learn here.")
    (tmp_path / "content.yaml").write_text("schema_version: 1\ncollections:\n" + "".join(entries))
    assert check_repository(tmp_path) == []
    return tmp_path


def missing_dates(root, path):
    prefix = path
    if prefix:
        prefix += "/"
    cohort = f"{prefix}cohorts/live/cohort.yaml"
    write_document(root, cohort, "Live", extra="delivery: live\n")
    return Diagnostic(
        path or ".",
        "/",
        "3.8",
        f"{cohort}: a published live cohort declares start_date and end_date",
    )


def malformed_lesson(root, path):
    lesson = f"{path}/01-core/01-lesson.md"
    target = root / lesson
    target.write_text(target.read_text().replace("title: Lesson\n", ""))
    return Diagnostic(lesson, "/title", "3.3", "required key title is missing")


def assert_graph(parsed):
    assert parsed.course.slug == "sample"
    assert parsed.course.title == "Course"
    (module,) = parsed.course.modules
    assert module.slug == "core"
    (unit,) = module.units
    assert (unit.slug, unit.title, unit.body) == ("lesson", "Lesson", "Learn here.\n")


def assert_rejected(result, collection, diagnostic):
    for run in (lambda: check_read(result, collection), lambda: parse_course(result, collection)):
        with pytest.raises(CurriculumParseError) as error:
            run()
        assert str(error.value) == diagnostic.render()


@pytest.mark.parametrize("broken", ["courses/alpha", "courses/beta", "courses/alpha-extra"])
def test_real_read_error_is_scoped_to_its_collection(tmp_path, broken):
    root = repository(tmp_path, ("courses/alpha", "courses/beta", "courses/alpha-extra"))
    diagnostic = malformed_lesson(root, broken)
    result = read_courses(root)
    assert result.errors == (diagnostic,)
    for collection in course_collections(result):
        if collection.path == broken:
            assert_rejected(result, collection, diagnostic)
            with pytest.raises(CurriculumParseError) as error:
                parse_course_repository(root, path=broken)
            assert str(error.value) == diagnostic.render()
            continue
        check_read(result, collection)
        assert_graph(parse_course(result, collection))
        assert_graph(parse_course_repository(root, path=collection.path))
    assert course_source_diagnostics(result) == []
    assert check_repository(root) == [diagnostic]
    with pytest.raises(CurriculumParseError) as error:
        check_read(result)
    assert str(error.value) == diagnostic.render()


@pytest.mark.parametrize("broken", ["courses/alpha", "courses/beta", "courses/alpha-extra"])
def test_read_errors_suppress_only_their_own_semantic_diagnostic(tmp_path, broken):
    root = repository(tmp_path, ("courses/alpha", "courses/beta", "courses/alpha-extra"))
    semantic = missing_dates(root, "courses/alpha")
    control = read_courses(root)
    assert control.errors == ()
    assert course_source_diagnostics(control) == [semantic]
    assert check_repository(root) == [semantic]
    primary = malformed_lesson(root, broken)
    result = read_courses(root)
    assert result.errors == (primary,)
    if broken == "courses/alpha":
        alpha, *_ = course_collections(result)
        assert_rejected(result, alpha, primary)
        assert course_source_diagnostics(result) == []
        assert check_repository(root) == [primary]
        return
    assert course_source_diagnostics(result) == [semantic]
    expected = sorted([primary, semantic], key=lambda item: item.sort_key)
    assert check_repository(root) == expected


@pytest.mark.parametrize(
    "paths, location",
    [(("",), "elsewhere/broken.md"), (("courses/alpha", "courses/beta"), "content.yaml")],
)
def test_synthetic_root_and_manifest_errors_preserve_real_collections(tmp_path, paths, location):
    """Inject located errors after a successful read: invalid manifests may hide collections."""
    root = repository(tmp_path, paths)
    result = read_courses(root)
    primary = Diagnostic(location, "/title", "3.3", "synthetic read error")
    result = replace(result, diagnostics=[primary])
    assert len(result.collections) == len(paths)
    for collection in course_collections(result):
        assert_rejected(result, collection, primary)
    assert course_source_diagnostics(result) == []
    semantic = missing_dates(root, paths[0])
    control = read_courses(root)
    assert course_source_diagnostics(control) == [semantic]
    assert course_source_diagnostics(replace(control, diagnostics=[primary])) == []
    with pytest.raises(CurriculumParseError) as error:
        check_read(result)
    assert str(error.value) == primary.render()


@pytest.mark.parametrize("location", ["courses/alpha/course.yaml", "content.yaml"])
def test_synthetic_warning_neither_rejects_nor_suppresses(tmp_path, location):
    """The real graphs remain intact while a warning is injected into their read result."""
    root = repository(tmp_path)
    warning = Diagnostic(location, "/", "3.3", "synthetic warning", severity="warning")
    result = replace(read_courses(root), diagnostics=[warning])
    assert result.errors == ()
    check_read(result)
    for collection in course_collections(result):
        check_read(result, collection)
        assert_graph(parse_course(result, collection))
    assert course_source_diagnostics(result) == []
    semantic = missing_dates(root, "courses/alpha")
    control = read_courses(root)
    assert course_source_diagnostics(control) == [semantic]
    assert course_source_diagnostics(replace(control, diagnostics=[warning])) == [semantic]
