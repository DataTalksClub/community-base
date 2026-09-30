"""Unsupported ordered cohort placement is refused before source mutation."""

import pytest

from community_base.content_sync.convert.courses import convert_course_repository
from tests.content_sync.test_convert_courses import COHORT, repository

COHORT_PATH = "cohorts/2026/cohort.yaml"
MODULE_FLOW = "flow:\n  - module:\n      source: 01-agentic-rag/module.yaml\n"
PROJECT_FLOW = MODULE_FLOW + "  - project: project-01\n"


def _snapshot(root):
    files = {}
    for path in root.rglob("*"):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _source(root, flow):
    other = COHORT.split("homework:\n")[0].replace("2026", "2027")
    other = other.replace("0ea85a46", "1ea85a46")
    return repository(
        root,
        **{COHORT_PATH: COHORT + flow, "cohorts/2027/cohort.yaml": other},
    )


def _assert_refusal(report):
    assert not report.ok
    assert [(item.path, item.rule) for item in report.refusals] == [(COHORT_PATH, "3.8")]
    assert "flow" in report.refusals[0].message
    assert "placement" in report.refusals[0].message
    assert report.verify() == []


@pytest.mark.parametrize("flow", [MODULE_FLOW, PROJECT_FLOW])
def test_ordered_flow_preserves_refused_scope_and_converts_other_scopes(tmp_path, flow):
    root = _source(tmp_path, flow)
    before = _snapshot(root)

    report = convert_course_repository(root)

    _assert_refusal(report)
    for path, body in before.items():
        if path.startswith("cohorts/2026/"):
            assert (root / path).read_bytes() == body
    other = root / "cohorts/2027/cohort.yaml"
    assert other.read_bytes() != before["cohorts/2027/cohort.yaml"]
    assert "schema_version" not in other.read_text()
    assert (root / "01-agentic-rag/module.yaml").read_bytes() != before[
        "01-agentic-rag/module.yaml"
    ]
    converted = _snapshot(root)
    _assert_refusal(convert_course_repository(root))
    assert _snapshot(root) == converted


@pytest.mark.parametrize("flow", [MODULE_FLOW, PROJECT_FLOW])
def test_dry_run_refuses_ordered_flow_without_writing_any_source(tmp_path, flow):
    root = _source(tmp_path, flow)
    before = _snapshot(root)

    report = convert_course_repository(root, apply=False)

    _assert_refusal(report)
    assert _snapshot(root) == before


@pytest.mark.parametrize("flow", ["", "flow: []\n"])
def test_absent_or_empty_legacy_flow_keeps_existing_conversion(tmp_path, flow):
    root = _source(tmp_path, flow)

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert report.verify() == []
    assert convert_course_repository(root).converted == 0
