"""Legacy list order and explicit unit order retain their separate meanings."""

from community_base.content_sync.convert.courses import convert_course_repository
from community_base.curriculum.parsers import parse_course_repository
from tests.content_sync.test_convert_courses import MODULE, UNIT, repository


def test_explicit_unit_order_stays_authoritative_when_legacy_list_agrees(tmp_path):
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
            "01-agentic-rag/03-later.md": UNIT.replace("next_url", "sort_order: 10\nnext_url"),
            "01-agentic-rag/01-earlier.md": "---\nsort_order: 20\n---\nEarlier body.\n",
        },
    )
    (root / "01-agentic-rag/01-intro.md").unlink()

    report = convert_course_repository(root)

    assert report.ok, report.render()
    units = parse_course_repository(root).course.modules[0].units
    assert [unit.title for unit in units] == ["Introduction", "Earlier filename"]
    assert [unit.sort_order for unit in units] == [10, 20]


def test_flat_equal_explicit_positions_keep_legacy_filename_tie_break(tmp_path):
    manifest = MODULE + (
        "  - content_id: 9a2b3c4d-0007-4000-8000-000000000001\n"
        "    title: Second\n    path: 02-second.md\n"
    )
    root = repository(
        tmp_path,
        **{
            "01-agentic-rag/module.yaml": manifest,
            "01-agentic-rag/01-intro.md": UNIT.replace("next_url", "sort_order: 10\nnext_url"),
            "01-agentic-rag/02-second.md": "---\nsort_order: 10\n---\nSecond body.\n",
        },
    )

    report = convert_course_repository(root)

    assert report.ok, report.render()
    units = parse_course_repository(root).course.modules[0].units
    assert [(unit.title, unit.sort_order) for unit in units] == [
        ("Introduction", 10),
        ("Second", 10),
    ]


def _ignore(root, path):
    (root / "content.yaml").write_text(
        f"schema_version: 1\ncollections:\n  - kind: course\n    path: .\nignore:\n  - {path}\n"
    )


def test_ignored_homework_sibling_does_not_require_mixed_order(tmp_path):
    root = repository(
        tmp_path,
        **{
            "01-agentic-rag/module.yaml": MODULE.replace("01-intro.md", "intro.md"),
            "01-agentic-rag/intro.md": UNIT,
            "01-agentic-rag/ignored/homework.yaml": "opaque: true\n",
        },
    )
    (root / "01-agentic-rag/01-intro.md").unlink()
    _ignore(root, "01-agentic-rag/ignored/**")
    ignored = root / "01-agentic-rag/ignored/homework.yaml"
    before = ignored.read_bytes()

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert ignored.read_bytes() == before
    assert parse_course_repository(root).course.modules[0].units[0].slug == "intro"
    assert report.verify() == []


def test_ignored_declared_unit_does_not_conflict_with_eligible_list_order(tmp_path):
    manifest = MODULE + (
        "  - content_id: 9a2b3c4d-0007-4000-8000-000000000001\n"
        "    title: Ignored\n    path: ignored.md\n    sort_order: 0\n"
    )
    root = repository(
        tmp_path,
        **{
            "01-agentic-rag/module.yaml": manifest,
            "01-agentic-rag/ignored.md": "---\n---\nIgnored body.\n",
        },
    )
    _ignore(root, "01-agentic-rag/ignored.md")
    ignored = root / "01-agentic-rag/ignored.md"
    before = ignored.read_bytes()

    report = convert_course_repository(root)

    assert report.ok, report.render()
    assert ignored.read_bytes() == before
    units = parse_course_repository(root).course.modules[0].units
    assert [(unit.slug, unit.sort_order) for unit in units] == [("intro", 1)]
    assert report.verify() == []
