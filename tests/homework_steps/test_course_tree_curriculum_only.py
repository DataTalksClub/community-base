"""Source validation does not depend on the optional coursework app."""

import shutil
from pathlib import Path

import pytest

from community_base.coursework.manifests import read_cohort_homework
from community_base.curriculum.parsers import course_collections, parse_course, read_courses
from community_base.curriculum.source import CurriculumParseError

DTC_REPO = Path(__file__).resolve().parents[1] / "curriculum/fixtures/dtc-repo"


def test_unbound_authored_answer_is_validated_without_coursework(tmp_path):
    root = tmp_path / "course"
    shutil.copytree(DTC_REPO, root)
    directory = root / "01-core/03-quiz"
    directory.mkdir()
    (directory / "homework.md").write_text("Instructions.\n")
    (directory / "homework.yaml").write_text(
        "content_id: 9a2b3c4d-0003-4000-8000-000000000009\n"
        "title: Invalid quiz\n"
        "questions:\n"
        "  - content_id: 9a2b3c4d-0006-4000-8000-000000000009\n"
        "    id: first\n"
        "    type: multiple_choice\n"
        "    prompt: Pick one\n"
        "    points: 1\n"
        "    options:\n"
        "      - {id: a, label: Alpha}\n"
        "    correct: '2'\n"
    )

    result = read_courses(root)
    collection = course_collections(result)[0]
    parsed = parse_course(result, collection)
    with pytest.raises(CurriculumParseError, match="correct"):
        read_cohort_homework(result, collection, parsed)
