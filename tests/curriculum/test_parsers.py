"""The one course parser: `FORMAT.md` section 3.8 onto the curriculum graph.

The first group of tests is the three defects issue C7.10 exists for. Neither
package course parser could read the real course repositories: one demanded
`schema_version: 1` in `course.yaml` where five of the six DataTalks.Club
repositories carry 2, one rejected the `prev_url` and `next_url` keys that 71
of the 72 `llm-zoomcamp` lessons carry, and the sync adapter skipped a
root-level `course.yaml`, which is where `ai-buildcamp-course` and
`python-course` keep theirs. Each has a test below naming it.
"""

import shutil

import pytest

from community_base.curriculum.parsers import (
    course_collections,
    parse_course,
    parse_course_repository,
    read_courses,
)
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.utils import AISL_CONTENT, AISL_ROOT, DTC_NESTED, DTC_REPO


def copy(fixture, tmp_path, name):
    target = tmp_path / name
    shutil.copytree(fixture, target)
    return target


def parse(fixture, path=None):
    return parse_course_repository(fixture, path=path)


def parse_all(fixture):
    result = read_courses(fixture)
    return [parse_course(result, collection) for collection in course_collections(result)]


# --------------------------------------------------------------------------
# The three defects
# --------------------------------------------------------------------------


def test_defect_a_course_manifest_is_not_gated_on_schema_version_one():
    """Defect one: the deleted DTC parser demanded `schema_version == 1` in every manifest.

    Five of the six DataTalks.Club course repositories are schema 2, so that
    gate rejected all of them. The version now lives in `content.yaml` and
    nowhere else (section 3.1), so no course, module or cohort manifest of any
    fixture carries one and all of them parse.
    """

    for fixture in (AISL_CONTENT, AISL_ROOT, DTC_REPO, DTC_NESTED):
        for manifest in fixture.rglob("*.yaml"):
            if manifest.name == "content.yaml":
                continue
            assert "schema_version" not in manifest.read_text()
        assert parse_all(fixture)


def test_defect_a_schema_version_left_in_a_course_manifest_is_named(tmp_path):
    """The other half of defect one: the key is reported, not silently obeyed."""

    root = copy(DTC_REPO, tmp_path, "schema-two")
    manifest = root / "course.yaml"
    manifest.write_text(f"schema_version: 2\n{manifest.read_text()}")

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "course.yaml" in str(error.value)
    assert "schema_version" in str(error.value)


@pytest.mark.parametrize("key, value", [("prev_url", "01-intro.md"), ("next_url", "03-rag.md")])
def test_defect_a_lesson_carrying_prev_url_is_rejected_with_the_file_and_key_named(
    tmp_path, key, value
):
    """Defect two: 71 of 72 `llm-zoomcamp` lessons carry `prev_url` and `next_url`.

    The keys do not exist in the format (section 3.7 derives previous and next
    from order), so the parser names the file and the key rather than failing
    for an unrelated reason.
    """

    root = copy(DTC_REPO, tmp_path, f"retired-{key}")
    unit = root / "01-core" / "01-lesson.md"
    unit.write_text(
        unit.read_text().replace("title: What is ML", f"title: What is ML\n{key}: {value}")
    )

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "01-core/01-lesson.md" in str(error.value)
    assert key in str(error.value)


@pytest.mark.parametrize("line", ["is_homework: true", "is_preview: true", "access: open"])
def test_defect_every_retired_unit_key_is_named(tmp_path, line):
    """`is_homework`, `is_preview` and `access` are retired with the same rule."""

    root = copy(AISL_ROOT, tmp_path, f"retired-{line.split(':')[0]}")
    unit = root / "01-intro" / "01-why-python.md"
    unit.write_text(unit.read_text().replace("title: Why Python", f"title: Why Python\n{line}"))

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "01-intro/01-why-python.md" in str(error.value)
    assert line.split(":")[0] in str(error.value)


def test_defect_a_root_level_course_yaml_with_no_schema_version_parses():
    """Defect three: the adapter skipped a `course.yaml` at the repository root.

    `ai-buildcamp-course` and `python-course` both keep theirs there and carry
    no `schema_version`, so the AISL parser ignored them and the DTC parser
    rejected them. A collection at `path: .` is now an ordinary course.
    """

    parsed = parse(AISL_ROOT)

    assert (AISL_ROOT / "course.yaml").is_file()
    assert "schema_version" not in (AISL_ROOT / "course.yaml").read_text()
    assert parsed.course.slug == "python"
    assert [module.slug for module in parsed.course.modules] == ["intro", "projects"]


# --------------------------------------------------------------------------
# The four fixture repositories
# --------------------------------------------------------------------------


def test_aisl_multi_course_repository_parses_every_course_collection():
    """One collection per course, so a repository of three imports three."""

    parsed = parse_all(AISL_CONTENT)

    assert [item.course.slug for item in parsed] == ["ai-hero", "agents"]


def test_aisl_course_graph():
    parsed = parse(AISL_CONTENT, path="courses/ai-hero")

    course = parsed.course
    assert course.slug == "ai-hero"
    assert course.title == "AI Hero Crash Course"
    assert course.required_level == 0
    assert course.default_unit_required_level == 5
    assert course.status == "published"
    assert "applied" in course.description
    assert course.github_repo_url == "https://github.com/example/ai-hero"
    assert course.tags == ("ai-agents", "crash-course")
    assert course.testimonials[0]["name"] == "Grace Hopper"
    assert course.testimonials[0]["company"] == "UNIVAC"
    assert [module.slug for module in course.modules] == ["welcome", "retrieval"]

    welcome = course.modules[0]
    assert "# Welcome" in welcome.overview
    assert [unit.slug for unit in welcome.units] == ["setup", "exercise"]
    assert welcome.units[0].required_level == 0
    assert welcome.units[0].video_url.endswith("/abc")
    assert welcome.units[0].body.startswith("Body for")
    assert course.modules[1].units[0].kind == "homework"
    assert course.modules[1].units[0].body.startswith("Write a retrieval")


def test_an_instructor_reference_resolves_against_the_person_collection():
    parsed = parse(AISL_CONTENT, path="courses/ai-hero")

    (instructor,) = parsed.course.instructors
    assert instructor.slug == "ada-lovelace"
    assert instructor.name == "Ada Lovelace"
    assert instructor.bio == "First programmer."


def test_aisl_root_course_graph():
    course = parse(AISL_ROOT).course

    assert course.required_level == 30
    assert course.default_unit_required_level is None
    intro, projects = course.modules
    assert [unit.slug for unit in intro.units] == ["why-python", "setup"]
    assert intro.units[1].timestamps == (
        {"time": "00:00", "title": "Intro"},
        {"time": "1:02:30", "title": "Wrap up"},
    )
    assert projects.is_bonus is True
    assert projects.available_after_days == 7
    session, extra = projects.units
    assert session.kind == "event"
    assert session.session_position == 1
    assert extra.is_bonus is True
    assert extra.required_level == 20


def test_dtc_course_graph():
    course = parse(DTC_REPO).course

    assert course.slug == "ml-zoomcamp"
    assert course.visible is True
    assert course.description == "Learn machine learning by building four projects."
    assert course.hashtag == "mlzoomcamp"
    assert course.docs_url == "https://example.com/docs"
    assert [module.slug for module in course.modules] == ["core", "advanced"]
    core = course.modules[0]
    assert [unit.slug for unit in core.units] == ["lesson", "homework"]
    assert core.units[0].video_url == "https://youtu.be/xyz"
    assert core.units[1].kind == "homework"


def test_dtc_cohort_places_a_subset_and_carries_its_homework_bindings():
    course = parse(DTC_REPO).course

    cohorts = {cohort.slug: cohort for cohort in course.cohorts}
    assert set(cohorts) == {"2024", "2026"}
    live = cohorts["2026"]
    assert live.mode == "cohort"
    assert live.start_date.isoformat() == "2026-09-07"
    assert live.registration_url == "https://example.com/register"
    assert live.module_refs == ("9a2b3c4d-0002-4000-8000-000000000001",)
    assert live.homework_bindings == (
        {
            "module": "core",
            "source": "homework/core/homework.yaml",
            "unit": "9a2b3c4d-0003-4000-8000-000000000002",
        },
    )


def test_an_archived_cohort_places_nothing():
    course = parse(DTC_REPO).course

    archived = {cohort.slug: cohort for cohort in course.cohorts}["2024"]
    assert archived.module_refs == ()
    assert (DTC_REPO / "cohorts" / "2024" / "README.md").is_file()


def test_two_module_levels_with_a_cohort_placing_a_subset():
    course = parse(DTC_NESTED).course

    week_one, week_two = course.modules
    assert week_one.available_after_days == 7
    assert week_one.units == ()
    topic_a, topic_b = week_one.children
    assert [child.slug for child in week_one.children] == ["topic-a", "topic-b"]
    assert [unit.slug for unit in topic_a.units] == ["section-overview"]
    assert [unit.slug for unit in topic_b.units] == ["section-overview"]
    assert topic_a.units[0].body.startswith("Overview for topic A")

    (cohort,) = course.cohorts
    assert cohort.mode == "self_paced"
    assert cohort.module_refs == (week_two.content_id,)


def test_a_course_with_no_cohorts_gets_one_self_paced_cohort():
    course = parse(AISL_ROOT).course

    (cohort,) = course.cohorts
    assert cohort.mode == "self_paced"
    assert cohort.slug == "self-paced"
    assert cohort.module_refs is None  # no placements: the full course tree


def test_a_unit_that_declares_no_level_leaves_the_course_default_to_answer():
    course = parse(AISL_CONTENT, path="courses/ai-hero").course

    exercise = course.modules[0].units[1]
    assert exercise.required_level is None
    assert course.default_unit_required_level == 5


# --------------------------------------------------------------------------
# What the parser refuses
# --------------------------------------------------------------------------


def test_a_cohort_placing_an_unknown_module_slug_names_it(tmp_path):
    root = copy(DTC_REPO, tmp_path, "unknown-module")
    manifest = root / "cohorts" / "2026" / "cohort.yaml"
    manifest.write_text(manifest.read_text().replace("  - core\n", "  - nope\n"))

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "cohorts/2026/cohort.yaml" in str(error.value)
    assert "nope" in str(error.value)


def test_a_homework_binding_naming_an_unknown_module_slug_is_rejected(tmp_path):
    root = copy(DTC_REPO, tmp_path, "unknown-binding")
    manifest = root / "cohorts" / "2026" / "cohort.yaml"
    manifest.write_text(manifest.read_text().replace("  - module: core", "  - module: nope"))

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "/homework/0/module" in str(error.value)


def test_archive_and_modules_together_are_rejected(tmp_path):
    root = copy(DTC_REPO, tmp_path, "archive-and-modules")
    manifest = root / "cohorts" / "2024" / "cohort.yaml"
    manifest.write_text(f"{manifest.read_text()}modules:\n  - core\n")

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "archive" in str(error.value)
    assert "modules" in str(error.value)


def test_a_published_live_cohort_declares_its_dates(tmp_path):
    root = copy(DTC_REPO, tmp_path, "no-dates")
    manifest = root / "cohorts" / "2026" / "cohort.yaml"
    manifest.write_text(
        manifest.read_text()
        .replace("start_date: 2026-09-07\n", "")
        .replace("end_date: 2027-01-31\n", "")
    )

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "start_date" in str(error.value)


def test_a_module_holding_both_submodules_and_units_is_rejected(tmp_path):
    root = copy(DTC_NESTED, tmp_path, "mixed")
    stray = root / "01-week-one" / "99-stray-unit.md"
    stray.write_text(
        "---\ncontent_id: 2b3c4d5e-000b-4000-8000-000000000001\n"
        "title: Stray\n---\nShould not be allowed here.\n"
    )

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "01-week-one" in str(error.value)


def test_three_module_levels_are_rejected(tmp_path):
    root = copy(DTC_NESTED, tmp_path, "deep")
    deep = root / "01-week-one" / "01-topic-a" / "01-too-deep"
    deep.mkdir()
    (deep / "module.yaml").write_text(
        "content_id: 2b3c4d5e-000c-4000-8000-000000000001\ntitle: Too deep\n"
    )

    with pytest.raises(CurriculumParseError) as error:
        parse(root)

    assert "01-too-deep" in str(error.value)


def test_a_repository_with_no_course_collection_parses_nothing(tmp_path):
    root = tmp_path / "no-course"
    root.mkdir()
    (root / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: person\n    path: people\n"
    )
    (root / "people").mkdir()

    assert parse_all(root) == []
    with pytest.raises(CurriculumParseError):
        parse(root)


def test_an_archived_cohort_keeps_its_notice_path(tmp_path):
    """Decision D38: the notice path survives the parse as written."""

    root = copy(DTC_REPO, tmp_path, "archive-notice")
    manifest = root / "cohorts" / "2024" / "cohort.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "notice_path: cohorts/2024/README.md",
            "notice_path: cohorts/2024/leaderboard.md",
        )
    )

    course = parse(root).course
    archived = {cohort.slug: cohort for cohort in course.cohorts}["2024"]

    assert archived.module_refs == ()


def test_an_empty_archive_mapping_still_archives(tmp_path):
    root = copy(DTC_REPO, tmp_path, "archive-empty")
    manifest = root / "cohorts" / "2024" / "cohort.yaml"
    manifest.write_text(
        manifest.read_text().replace(
            "archive:\n  notice_path: cohorts/2024/README.md\n", "archive: {}\n"
        )
    )

    course = parse(root).course
    archived = {cohort.slug: cohort for cohort in course.cohorts}["2024"]

    assert archived.module_refs == ()
