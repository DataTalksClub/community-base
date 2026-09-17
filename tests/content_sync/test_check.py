import io
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from community_base.content_sync.check import check_repository, heading_ids, main, run_check

FIXTURES = Path(__file__).parent / "fixtures"
VALID = ("valid_course", "valid_multi", "valid_docs")

# One malformed repository per rule of sections 3.1 to 3.7 and of the dialect,
# with the diagnostic each must produce.
INVALID = (
    ("no_manifest", "3.1", "content.yaml", "every synced repository needs this file"),
    ("bad_schema_version", "3.1", "content.yaml", "must be 1"),
    ("unknown_kind", "3.1", "content.yaml", "unknown kind: podcast"),
    ("nested_collections", "3.1", "content.yaml", "collections never nest"),
    ("root_collection_with_others", "3.1", "content.yaml", "no other collection may be declared"),
    ("missing_front_matter", "3.2", "wiki/a-page.md", "starts with --- and YAML front matter"),
    ("manifest_not_mapping", "3.2", "course.yaml", "top level must be a mapping"),
    ("unknown_key", "3.3", "wiki/a-page.md", "unknown top-level key: layout"),
    ("missing_content_id", "3.3", "wiki/a-page.md", "required key content_id is missing"),
    ("bad_uuid", "3.3", "wiki/a-page.md", "must be a UUID"),
    ("bad_level", "3.3", "wiki/a-page.md", "must be an integer or one of"),
    ("forbidden_date", "3.3", "wiki/a-page.md", "date is forbidden on this kind"),
    ("missing_date", "3.3", "articles/a-post/index.md", "required key date is missing"),
    ("date_prefix", "3.4", "wiki/25-02-26-a-page.md", "names carry no date prefix"),
    ("duplicate_content_id", "3.4", "wiki/second.md", "is already used by wiki/first.md"),
    ("duplicate_slug", "3.4", "wiki/02-intro.md", "two siblings resolve to the slug 'intro'"),
    ("bad_slug_name", "3.4", "wiki/A_Bad_Name.md", "rename the file or declare a slug"),
    ("wiki_subdirectory", "3.5", "wiki/section", "no subdirectories apart from assets"),
    ("docs_missing_index", "3.5", "docs/01-general", "a tree node must contain index.md"),
    (
        "docs_too_deep",
        "3.5",
        "docs/01-a/02-b/03-c/04-d/05-e",
        "nesting is deeper than 4 levels below the collection",
    ),
    (
        "course_mixed_module",
        "3.5",
        "01-module",
        "either submodule directories or unit files",
    ),
    ("missing_asset", "3.6", "wiki/a-page.md", "does not exist"),
    ("absolute_asset", "3.6", "wiki/a-page.md", "must be a relative path"),
    ("escaping_asset", "3.6", "wiki/a-page.md", "leaves the repository"),
    ("bad_asset_type", "3.6", "wiki/a-page.md", "asset type is not allowed"),
    ("http_image", "3.6", "wiki/a-page.md", "http:// references are not allowed"),
    ("ignored_asset", "3.6", "wiki/a-page.md", "is ignored by content.yaml"),
    ("unresolved_link", "3.7", "wiki/a-page.md", "resolves to no document of this collection"),
    ("bad_fragment", "3.7", "wiki/a-page.md", "no heading 'setup' in wiki/b-page.md"),
    ("unresolved_reference", "3.7", "wiki/a-page.md", "unresolved reference"),
    ("unknown_reference_kind", "3.7", "wiki/a-page.md", "unknown kind in a typed reference"),
    ("liquid", "4.1", "wiki/a-page.md", "Liquid is not part of the dialect"),
    ("kramdown", "4.1", "wiki/a-page.md", "kramdown attribute lists"),
    ("wikilink", "4.1", "wiki/a-page.md", "[[wikilinks]] are not part of the dialect"),
    ("image_token", "4.1", "wiki/a-page.md", "{IMAGE:id} tokens"),
    ("bad_embed", "4.1", "wiki/a-page.md", "embed type must be youtube or loom"),
)


@pytest.mark.parametrize("name", VALID)
def test_a_valid_repository_reports_nothing(name):
    assert check_repository(FIXTURES / name) == []


@pytest.mark.parametrize("name", VALID)
def test_a_valid_repository_exits_zero(name):
    assert main([str(FIXTURES / name)]) == 0


@pytest.mark.parametrize(
    ("name", "rule", "path", "message"),
    INVALID,
    ids=[entry[0] for entry in INVALID],
)
def test_a_malformed_repository_is_rejected_with_a_path_and_a_pointer(name, rule, path, message):
    diagnostics = check_repository(FIXTURES / "invalid" / name)

    matching = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.rule == rule
        and diagnostic.path == path
        and message in diagnostic.message
        and diagnostic.severity == "error"
    ]
    assert matching, "\n".join(diagnostic.render() for diagnostic in diagnostics)
    assert matching[0].pointer.startswith("/")
    assert main([str(FIXTURES / "invalid" / name)]) == 1


def test_every_diagnostic_carries_a_path_and_a_pointer():
    for name, *_ in INVALID:
        for diagnostic in check_repository(FIXTURES / "invalid" / name):
            assert diagnostic.path
            assert diagnostic.pointer.startswith("/")
            assert diagnostic.rule
            assert diagnostic.render().startswith(f"{diagnostic.path}")


def test_strict_references_false_degrades_to_a_warning():
    diagnostics = check_repository(FIXTURES / "lenient_references")

    assert [diagnostic.severity for diagnostic in diagnostics] == ["warning"]
    assert run_check(FIXTURES / "lenient_references", stdout=io.StringIO()) == 0


def test_a_path_that_is_not_a_repository_is_one_diagnostic():
    diagnostics = check_repository(FIXTURES / "no-such-repository")

    assert [diagnostic.rule for diagnostic in diagnostics] == ["3.1"]


def test_run_check_counts_errors_and_writes_the_report():
    stream = io.StringIO()

    errors = run_check(FIXTURES / "invalid" / "liquid", stdout=stream)

    assert errors == 1
    assert "[4.1]" in stream.getvalue()
    assert "1 error(s), 0 warning(s)" in stream.getvalue()


def test_the_module_and_the_management_command_agree():
    """Section 3.10: two entry points, one implementation."""

    for name in (*VALID, "lenient_references"):
        path = str(FIXTURES / name)
        module_report = io.StringIO()
        command_report = io.StringIO()

        run_check(path, stdout=module_report)
        call_command("check_content", path, stdout=command_report)

        assert command_report.getvalue() == module_report.getvalue()


@pytest.mark.parametrize("name", [entry[0] for entry in INVALID])
def test_the_management_command_reports_what_the_module_reports(name):
    path = str(FIXTURES / "invalid" / name)
    module_report = io.StringIO()
    command_report = io.StringIO()

    errors = run_check(path, stdout=module_report)
    with pytest.raises(CommandError, match="does not match the content format"):
        call_command("check_content", path, stdout=command_report)

    assert errors
    assert command_report.getvalue() == module_report.getvalue()


def test_the_module_entry_point_runs_as_a_process():
    result = subprocess.run(
        [sys.executable, "-m", "community_base.content_sync.check", str(FIXTURES / "valid_multi")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "matches the content format version 1" in result.stdout


def test_a_site_kind_module_can_be_imported_before_checking():
    path = FIXTURES / "invalid" / "unknown_reference_kind"

    without = check_repository(path)
    with_site_kind = check_repository(path, kind_modules=["tests.content_sync.site_kind_module"])

    assert [diagnostic.rule for diagnostic in without] == ["3.7"]
    assert with_site_kind == []


def test_heading_ids_follow_the_kept_algorithm():
    body = "# A/B Testing\n\n## Setup\n\n```\n## Not a heading\n```\n\n## Setup\n"

    assert heading_ids(body) == [
        (1, "a-b-testing", "A/B Testing"),
        (2, "setup", "Setup"),
        (2, "setup-1", "Setup"),
    ]


def test_a_leading_h1_equal_to_the_title_is_a_warning(tmp_path):
    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
    )
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "a-page.md").write_text(
        '---\ncontent_id: "88888888-8888-4888-8888-888888888888"\ntitle: A Page\n---\n\n'
        "# A Page\n\nBody.\n"
    )

    diagnostics = check_repository(tmp_path)

    assert [(diagnostic.rule, diagnostic.severity) for diagnostic in diagnostics] == [
        ("4.1", "warning")
    ]


def test_an_ignored_file_is_not_an_asset(tmp_path):
    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
        'ignore:\n  - "**/drafts/**"\n'
    )
    (tmp_path / "wiki" / "drafts").mkdir(parents=True)
    (tmp_path / "wiki" / "drafts" / "cover.png").write_bytes(b"\x89PNG")
    (tmp_path / "wiki" / "a-page.md").write_text(
        '---\ncontent_id: "88888888-8888-4888-8888-888888888888"\ntitle: A Page\n'
        "image: drafts/cover.png\n---\n\nBody.\n"
    )

    diagnostics = check_repository(tmp_path)

    assert [diagnostic.rule for diagnostic in diagnostics] == ["3.6"]
    assert "is ignored by content.yaml" in diagnostics[0].message
