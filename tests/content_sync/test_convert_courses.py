"""The course conversion of `C7.12`: what it rewrites, and what it refuses."""

from pathlib import Path

import yaml

from community_base.content_sync.check import check_repository
from community_base.content_sync.convert.courses import convert_course_repository

COURSE = """schema_version: 2
content_id: e79727f3-f540-4176-ae98-9b9cb42abdc7
slug: llm-zoomcamp
title: LLM Zoomcamp
current_cohort: "2026"
cohorts:
  - identifier: "2026"
    content: root
description: A course.
urls:
  repository: https://github.com/DataTalksClub/llm-zoomcamp
  faq: https://datatalks.club/faq/llm-zoomcamp.html
hashtag: llmzoomcamp
published: true
"""

MODULE = """schema_version: 2
content_id: d9ca5cb3-b94c-4281-be7d-a2462559f02b
title: "Module 1"
units:
  - content_id: 1e8059d3-1c63-47f6-b0a1-9b21c96ca1c6
    title: "Introduction"
    path: 01-intro.md
"""

UNIT = """---
video_url: "https://www.youtube.com/watch?v=x"
next_url: 02-environment.md
---
# Introduction

The lesson body.
"""

COHORT = """schema_version: 2
content_id: 0ea85a46-bd6b-4f21-82fe-317954d8be32
identifier: "2026"
course: llm-zoomcamp
delivery: live
published: true
start_date: "2026-08-24"
end_date: "2026-10-12"
curriculum: current
homework:
  - module: 01-agentic-rag
    source: cohorts/2026/homework/01-agentic-rag/homework.yaml
"""

HOMEWORK = """schema_version: 2
content_id: 9a2b3c4d-0005-4000-8000-000000000001
title: Homework 1
due_at: "2026-09-01T23:59:00+00:00"
questions:
  - content_id: 9a2b3c4d-0006-4000-8000-000000000001
    id: q1
    type: free_form
    prompt: What is RAG?
    points: 1
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def repository(root: Path, **overrides: str) -> Path:
    files = {
        "course.yaml": COURSE,
        "01-agentic-rag/module.yaml": MODULE,
        "01-agentic-rag/01-intro.md": UNIT,
        "cohorts/2026/cohort.yaml": COHORT,
        "cohorts/2026/homework/01-agentic-rag/homework.yaml": HOMEWORK,
    }
    files.update(overrides)
    return write(root, files)


def load(root: Path, name: str):
    return yaml.safe_load((root / name).read_text())


def front_matter(root: Path, name: str):
    text = (root / name).read_text()
    return yaml.safe_load(text.split("---", 2)[1])


# --- what it writes -----------------------------------------------------------


def test_the_manifest_declares_the_one_course_collection(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)

    assert load(root, "content.yaml")["schema_version"] == 1
    assert load(root, "content.yaml")["collections"] == [{"kind": "course", "path": "."}]


def test_the_course_manifest_flattens_urls_and_drops_the_version(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)
    course = load(root, "course.yaml")

    assert "schema_version" not in course
    assert "urls" not in course
    assert "cohorts" not in course
    assert course["repository_url"] == "https://github.com/DataTalksClub/llm-zoomcamp"
    assert course["faq_url"] == "https://datatalks.club/faq/llm-zoomcamp.html"


def test_a_unit_takes_its_identity_from_the_module_manifest(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)
    unit = front_matter(root, "01-agentic-rag/01-intro.md")

    assert unit["content_id"] == "1e8059d3-1c63-47f6-b0a1-9b21c96ca1c6"
    assert unit["title"] == "Introduction"
    assert "next_url" not in unit
    assert "units" not in load(root, "01-agentic-rag/module.yaml")


def test_the_leading_h1_that_repeats_the_title_is_removed(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)

    assert "# Introduction" not in (root / "01-agentic-rag/01-intro.md").read_text()
    assert "The lesson body." in (root / "01-agentic-rag/01-intro.md").read_text()


def test_a_cohort_gains_the_title_decision_d34_requires(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)
    cohort = load(root, "cohorts/2026/cohort.yaml")

    assert cohort["title"] == "LLM Zoomcamp 2026"
    assert "identifier" not in cohort
    assert "course" not in cohort
    assert "curriculum" not in cohort


def test_a_homework_binding_is_made_cohort_relative(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)
    cohort = load(root, "cohorts/2026/cohort.yaml")

    assert cohort["homework"] == [
        {"module": "agentic-rag", "source": "homework/01-agentic-rag/homework.yaml"}
    ]


def test_an_archived_cohort_keeps_its_notice_path(tmp_path):
    archived = (
        COHORT.split("homework:")[0].replace("curriculum: current", "curriculum: github_archive")
        + "archive:\n  notice_path: cohorts/2026/leaderboard.md\n"
    )
    root = repository(tmp_path, **{"cohorts/2026/cohort.yaml": archived})

    convert_course_repository(root)

    assert load(root, "cohorts/2026/cohort.yaml")["archive"] == {
        "notice_path": "cohorts/2026/leaderboard.md"
    }


def test_a_key_the_format_cannot_express_moves_under_extra(tmp_path):
    root = repository(tmp_path, **{"course.yaml": COURSE + "maven_course_key: from-rag\n"})

    convert_course_repository(root)

    assert load(root, "course.yaml")["extra"] == {"maven_course_key": "from-rag"}


# --- what it refuses ----------------------------------------------------------


def test_a_units_entry_naming_a_missing_file_is_refused(tmp_path):
    broken = MODULE + "  - content_id: 9a2b3c4d-0007-4000-8000-000000000001\n    path: 99-gone.md\n"
    root = repository(tmp_path, **{"01-agentic-rag/module.yaml": broken})

    report = convert_course_repository(root)

    assert not report.ok
    assert "99-gone.md" in report.refusals[0].message
    assert load(root, "01-agentic-rag/module.yaml")["schema_version"] == 2


def test_a_contradicted_unit_identity_is_refused(tmp_path):
    root = repository(
        tmp_path,
        **{
            "01-agentic-rag/01-intro.md": UNIT.replace(
                "video_url", "content_id: 9a2b3c4d-0008-4000-8000-000000000001\nvideo_url"
            )
        },
    )

    report = convert_course_repository(root)

    assert [item.rule for item in report.refusals] == ["3.4"]


def test_a_course_manifest_with_no_description_is_refused(tmp_path):
    root = repository(tmp_path, **{"course.yaml": COURSE.replace("description: A course.\n", "")})

    report = convert_course_repository(root)

    assert "description" in report.refusals[0].message


def test_a_cohort_whose_curriculum_and_archive_disagree_is_refused(tmp_path):
    root = repository(
        tmp_path,
        **{
            "cohorts/2026/cohort.yaml": COHORT.replace(
                "curriculum: current", "curriculum: github_archive"
            )
        },
    )

    report = convert_course_repository(root)

    assert [item.rule for item in report.refusals] == ["3.8"]


def test_a_refused_file_is_left_exactly_as_it_was(tmp_path):
    root = repository(tmp_path, **{"course.yaml": COURSE.replace("description: A course.\n", "")})
    before = (root / "cohorts/2026/cohort.yaml").read_text()

    convert_course_repository(root)

    assert (root / "cohorts/2026/cohort.yaml").read_text() != before  # other files still convert
    assert "schema_version" not in (root / "course.yaml").read_text()


# --- the two properties the issue asks for ------------------------------------


def test_the_conversion_accounts_for_every_file(tmp_path):
    root = repository(tmp_path, **{"images/cover.png": "not really a png"})

    report = convert_course_repository(root)

    assert report.verify() == []
    assert set(report.before) <= set(report.after)


def test_running_it_twice_produces_no_second_change(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)
    after = {path: (root / path).read_bytes() for path in _paths(root)}
    second = convert_course_repository(root)

    assert second.converted == 0
    assert {path: (root / path).read_bytes() for path in _paths(root)} == after


def test_a_converted_repository_passes_the_validator(tmp_path):
    root = repository(tmp_path)

    convert_course_repository(root)

    assert [item.render() for item in check_repository(root)] == []


def test_a_dry_run_writes_nothing_and_reports_the_same(tmp_path):
    root = repository(tmp_path)
    before = {path: (root / path).read_bytes() for path in _paths(root)}

    report = convert_course_repository(root, apply=False)

    assert report.converted > 0
    assert {path: (root / path).read_bytes() for path in _paths(root)} == before


def _paths(root: Path) -> list[str]:
    return sorted(item.relative_to(root).as_posix() for item in root.glob("**/*") if item.is_file())
