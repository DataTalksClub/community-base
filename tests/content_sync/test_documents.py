import hashlib
import shutil
import sys
from pathlib import Path

import pytest

from community_base.content_sync.check import check_repository
from community_base.content_sync.checkout import ImmutableCheckout
from community_base.content_sync.documents import read_repository
from community_base.content_sync.kinds.base import applied_defaults, default_value, resolve_level
from community_base.content_sync.kinds.course import UNIT
from community_base.content_sync.resolution import resolve_repository

FIXTURES = Path(__file__).parent / "fixtures"
VALID = ("valid_course", "valid_multi", "valid_docs", "lenient_references")

WIKI_MANIFEST = "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
PAGE = (
    '---\ncontent_id: "88888888-8888-4888-8888-888888888888"\ntitle: A Page\n---\n\nA page body.\n'
)


def write_wiki(root: Path, name: str, text: str = PAGE, manifest: str = WIKI_MANIFEST) -> Path:
    """One wiki repository holding one page, for a rule that needs no fixture."""

    (root / "content.yaml").write_text(manifest)
    (root / "wiki").mkdir(exist_ok=True)
    page = root / "wiki" / name
    page.write_text(text)
    return page


# --- what a valid repository yields ------------------------------------------


def test_a_docs_tree_yields_one_document_per_page_with_its_derived_path():
    result = read_repository(FIXTURES / "valid_docs")

    assert result.ok
    found = {(item.raw.path, item.path, item.slug, item.sort_order) for item in result.documents}
    assert found == {
        ("docs/index.md", "", "docs", 0),
        ("docs/01-general/index.md", "general", "general", 1),
        ("docs/01-general/01-joining.md", "general/joining", "joining", 1),
        ("docs/02-courses/index.md", "courses", "courses", 2),
        ("docs/02-courses/01-llm-zoomcamp/index.md", "courses/llm-zoomcamp", "llm-zoomcamp", 1),
        (
            "docs/02-courses/01-llm-zoomcamp/01-joining.md",
            "courses/llm-zoomcamp/joining",
            "joining",
            1,
        ),
    }


def test_a_docs_tree_repeats_a_leaf_slug_under_different_parents():
    """Section 3.8, docs: `joining` twice is legal because the paths differ."""

    result = read_repository(FIXTURES / "valid_docs")

    joining = sorted(item.path for item in result.documents if item.slug == "joining")
    assert joining == ["courses/llm-zoomcamp/joining", "general/joining"]
    assert result.ok


def test_a_course_yields_its_manifest_modules_units_cohort_and_homework():
    result = read_repository(FIXTURES / "valid_course")

    assert result.ok
    assert {(item.part.name, item.raw.path, item.path) for item in result.documents} == {
        ("course", "course.yaml", "llm-zoomcamp"),
        ("module", "01-agentic-rag/module.yaml", "llm-zoomcamp/agentic-rag"),
        ("unit", "01-agentic-rag/01-intro.md", "llm-zoomcamp/agentic-rag/intro"),
        ("unit", "01-agentic-rag/02-environment.md", "llm-zoomcamp/agentic-rag/environment"),
        ("cohort", "cohorts/2026/cohort.yaml", "2026"),
        ("homework", "cohorts/2026/homework/01-agentic-rag/homework.yaml", "2026/agentic-rag"),
    }


def test_a_course_at_the_repository_root_takes_the_slug_its_manifest_declares():
    """Section 3.8: `path: .` has no directory name for the default to read."""

    course = read_repository(FIXTURES / "valid_course").by_part("course")[0]

    assert course.slug == "llm-zoomcamp"
    assert course.values["title"] == "LLM Zoomcamp"


def test_a_unit_carries_its_kind_keys_and_its_unrendered_body():
    intro = next(
        item
        for item in read_repository(FIXTURES / "valid_course").documents
        if item.raw.path == "01-agentic-rag/01-intro.md"
    )

    assert intro.part is UNIT
    assert intro.is_document
    assert intro.values["video_url"].startswith("https://")
    assert intro.body.strip().startswith("In this module")
    assert "---" not in intro.body


def test_a_multi_collection_repository_separates_its_collections():
    result = read_repository(FIXTURES / "valid_multi")

    assert result.ok
    assert [item.path for item in result.by_kind("wiki")] == ["a-b-testing", "power-analysis"]
    assert [item.path for item in result.by_kind("article")] == ["crisp-dm-for-ai"]
    assert [item.path for item in result.by_kind("person")] == ["alexey-grigorev"]


def test_a_data_file_is_keyed_by_its_path_below_the_collection_root():
    """Section 3.8: a file stem cannot keep `graph/graph.json` distinct."""

    data = read_repository(FIXTURES / "valid_multi").by_kind("data")

    assert sorted(item.path for item in data) == ["graph/graph", "tiers"]
    assert sorted(item.key for item in data) == ["data:graph/graph", "data:tiers"]


def test_a_data_file_carries_its_parsed_content_untouched(tmp_path):
    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: data\n    path: data\n"
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "tiers.yaml").write_text("- first\n- second\n")

    result = read_repository(tmp_path)

    assert result.ok
    assert result.documents[0].content == ["first", "second"]


def test_the_manifest_defaults_are_read_once(tmp_path):
    lenient = read_repository(FIXTURES / "lenient_references").manifest
    multi = read_repository(FIXTURES / "valid_multi").manifest
    course = read_repository(FIXTURES / "valid_course").manifest

    assert (lenient.strict_references, lenient.theme_pairs) == (False, False)
    assert (multi.strict_references, multi.theme_pairs) == (True, True)
    assert course.ignore == ("**/code/**", "etc/**")


@pytest.mark.parametrize("name", VALID)
def test_reading_a_valid_repository_reports_nothing(name):
    result = read_repository(FIXTURES / name)

    assert result.diagnostics == ()
    assert result.ok


# --- ordering, identity and the derived record --------------------------------


def test_sort_order_comes_from_the_name_prefix_and_front_matter_wins(tmp_path):
    (tmp_path / "content.yaml").write_text(WIKI_MANIFEST)
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "01-first.md").write_text(PAGE)
    (tmp_path / "wiki" / "002-second.md").write_text(
        PAGE.replace("88888888", "77777777").replace(
            "title: A Page", "title: A Page\nsort_order: 9"
        )
    )

    result = read_repository(tmp_path)

    assert {(item.slug, item.sort_order) for item in result.documents} == {
        ("first", 1),
        ("second", 9),
    }
    assert [item.slug for item in sorted(result.documents, key=lambda item: item.sort_key)] == [
        "first",
        "second",
    ]


def test_required_level_is_inherited_from_the_parent_item(tmp_path):
    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: docs\n    path: docs\n"
    )
    (tmp_path / "docs" / "01-paid").mkdir(parents=True)
    (tmp_path / "docs" / "index.md").write_text(PAGE)
    (tmp_path / "docs" / "01-paid" / "index.md").write_text(
        PAGE.replace("88888888", "77777777").replace(
            "title: A Page", "title: A Page\nrequired_level: premium"
        )
    )
    (tmp_path / "docs" / "01-paid" / "01-leaf.md").write_text(PAGE.replace("88888888", "66666666"))

    levels = {item.path: item.required_level for item in read_repository(tmp_path).documents}

    assert levels == {"": 0, "paid": 30, "paid/leaf": 30}


def test_the_checksum_covers_the_derived_record_and_not_the_bytes_alone(tmp_path):
    """The same bytes in two places are two records, and differ."""

    here = tmp_path / "here"
    there = tmp_path / "there"
    for root in (here, there):
        root.mkdir()
    first = write_wiki(here, "01-a-page.md")
    second = write_wiki(there, "02-a-page.md")

    assert first.read_bytes() == second.read_bytes()
    assert hashlib.sha256(first.read_bytes()).hexdigest() == (
        hashlib.sha256(second.read_bytes()).hexdigest()
    )

    one = read_repository(here).documents[0]
    other = read_repository(there).documents[0]

    assert one.sort_order != other.sort_order
    assert one.checksum != other.checksum


def test_the_checksum_is_stable_for_the_same_repository_read_twice():
    first = read_repository(FIXTURES / "valid_docs").documents
    second = read_repository(FIXTURES / "valid_docs").documents

    assert [item.checksum for item in first] == [item.checksum for item in second]
    assert len({item.checksum for item in first}) == len(first)


def test_a_renamed_file_keeps_its_content_id_and_changes_its_checksum(tmp_path):
    """Section 3.4: `content_id` is the upsert key, the checksum is the change."""

    before = read_repository(write_wiki(tmp_path, "a-page.md").parents[1]).documents[0]
    (tmp_path / "wiki" / "a-page.md").rename(tmp_path / "wiki" / "renamed.md")
    after = read_repository(tmp_path).documents[0]

    assert before.content_id == after.content_id
    assert (before.slug, after.slug) == ("a-page", "renamed")
    assert before.checksum != after.checksum


def test_values_carry_the_registry_defaults_and_the_declared_keys(tmp_path):
    write_wiki(tmp_path, "a-page.md")

    values = read_repository(tmp_path).documents[0].values

    assert values["status"] == "published"
    assert values["summary"] == ""
    assert values["tags"] == []
    assert values["extra"] == {}
    assert values["related"] == []
    assert values["title"] == "A Page"
    assert "date" not in values


def test_default_value_and_resolve_level_come_from_the_registry():
    assert default_value(UNIT.keys["is_bonus"]) is False
    assert default_value(UNIT.keys["timestamps"]) == []
    assert default_value(UNIT.keys["video_url"]) is None
    assert applied_defaults({"kind": "event"}, UNIT)["kind"] == "event"
    assert resolve_level("premium") == 30
    assert resolve_level(7) == 7
    assert resolve_level(None) is None


def test_a_checkout_and_a_directory_read_the_same_documents():
    """Section 3.10 reads a directory; a sync reads an immutable checkout."""

    from_directory = read_repository(FIXTURES / "valid_multi")
    with ImmutableCheckout(FIXTURES / "valid_multi") as checkout:
        from_checkout = read_repository(checkout)

    assert [item.raw.path for item in from_checkout.documents] == [
        item.raw.path for item in from_directory.documents
    ]
    assert [item.checksum for item in from_checkout.documents] == [
        item.checksum for item in from_directory.documents
    ]


# --- bounded, named errors ----------------------------------------------------

BOUNDED = (
    ("missing_content_id", "wiki/a-page.md", "/content_id", "required key content_id is missing"),
    ("duplicate_content_id", "wiki/second.md", "/content_id", "is already used by wiki/first.md"),
    ("unknown_key", "wiki/a-page.md", "/layout", "unknown top-level key: layout"),
    ("missing_front_matter", "wiki/a-page.md", "/", "starts with --- and YAML front matter"),
    ("duplicate_slug", "wiki/02-intro.md", "/slug", "two siblings resolve to the slug 'intro'"),
    ("wiki_subdirectory", "wiki/section", "/", "no subdirectories apart from assets"),
    (
        "docs_too_deep",
        "docs/01-a/02-b/03-c/04-d/05-e",
        "/",
        "nesting is deeper than 4 levels below the collection",
    ),
    ("no_manifest", "content.yaml", "/", "every synced repository needs this file"),
)


@pytest.mark.parametrize(
    ("name", "path", "pointer", "message"), BOUNDED, ids=[entry[0] for entry in BOUNDED]
)
def test_a_malformed_repository_is_one_bounded_error_naming_the_file(name, path, pointer, message):
    result = read_repository(FIXTURES / "invalid" / name)

    rendered = "\n".join(item.render() for item in result.diagnostics)
    matching = [
        item
        for item in result.errors
        if item.path == path and item.pointer == pointer and message in item.message
    ]
    assert matching, rendered
    assert not result.ok


def test_every_violation_in_a_collection_is_reported_in_one_pass(tmp_path):
    """Step 8: the toolkit lists them, it does not stop at the first."""

    (tmp_path / "content.yaml").write_text(WIKI_MANIFEST)
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "no-id.md").write_text("---\ntitle: No Id\n---\n\nBody.\n")
    (tmp_path / "wiki" / "no-front-matter.md").write_text("Body without front matter.\n")
    (tmp_path / "wiki" / "unknown.md").write_text(
        PAGE.replace("title: A Page", "title: A Page\nlayout: default")
    )

    result = read_repository(tmp_path)

    assert sorted((item.path, item.pointer) for item in result.errors) == [
        ("wiki/no-front-matter.md", "/"),
        ("wiki/no-id.md", "/content_id"),
        ("wiki/unknown.md", "/layout"),
    ]


def test_a_path_that_is_not_a_repository_is_one_diagnostic():
    result = read_repository(FIXTURES / "no-such-repository")

    assert [item.rule for item in result.diagnostics] == ["3.1"]
    assert result.documents == ()


def test_an_unreadable_manifest_stops_that_source(tmp_path):
    (tmp_path / "content.yaml").write_text("schema_version: 1\ncollections: [\n")

    result = read_repository(tmp_path)

    assert [(item.path, item.rule) for item in result.diagnostics] == [("content.yaml", "3.2")]
    assert result.documents == ()


def test_a_site_kind_module_can_be_imported_before_reading(tmp_path):
    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: podcast\n    path: podcast\n"
    )
    (tmp_path / "podcast").mkdir()

    without = read_repository(tmp_path)
    # The registry is reset around every test in this app, so the module has to
    # run again rather than come back from the import cache.
    sys.modules.pop("tests.content_sync.site_kind_module", None)
    with_site_kind = read_repository(tmp_path, kind_modules=["tests.content_sync.site_kind_module"])

    assert [item.rule for item in without.diagnostics] == ["3.1"]
    assert with_site_kind.ok


# --- the toolkit and the validator read one repository, once ------------------

# Every fixture, and what each of the two entry points makes of it. The toolkit
# is both halves of the format: `read_repository` for sections 3.1 to 3.5 and
# `resolve_repository` for the assets and cross-references of sections 3.6 and
# 3.7. `check_content` is the toolkit plus the markdown dialect of section 4.1,
# and nothing else. A fixture the validator rejects and the toolkit accepts is
# named here with the rule that separates them, so that a rule cannot move
# across the boundary unnoticed; every remaining difference is a dialect rule,
# which rejects a construct rather than resolves a destination.
PARITY = (
    ("valid_course", "accept", "accept", ""),
    ("valid_multi", "accept", "accept", ""),
    ("valid_docs", "accept", "accept", ""),
    ("lenient_references", "accept", "accept", ""),
    ("invalid/absolute_asset", "reject", "reject", ""),
    ("invalid/bad_asset_type", "reject", "reject", ""),
    ("invalid/bad_embed", "reject", "accept", "4.1 embed fence"),
    ("invalid/bad_fragment", "reject", "reject", ""),
    ("invalid/bad_level", "reject", "reject", ""),
    ("invalid/bad_schema_version", "reject", "reject", ""),
    ("invalid/bad_slug_name", "reject", "reject", ""),
    ("invalid/bad_uuid", "reject", "reject", ""),
    ("invalid/course_mixed_module", "reject", "reject", ""),
    ("invalid/date_prefix", "reject", "reject", ""),
    ("invalid/docs_missing_index", "reject", "reject", ""),
    ("invalid/docs_too_deep", "reject", "reject", ""),
    ("invalid/duplicate_content_id", "reject", "reject", ""),
    ("invalid/duplicate_slug", "reject", "reject", ""),
    ("invalid/escaping_asset", "reject", "reject", ""),
    ("invalid/forbidden_date", "reject", "reject", ""),
    ("invalid/http_image", "reject", "reject", ""),
    ("invalid/ignored_asset", "reject", "reject", ""),
    ("invalid/image_token", "reject", "accept", "4.1 body token"),
    ("invalid/kramdown", "reject", "accept", "4.1 attribute list"),
    ("invalid/liquid", "reject", "accept", "4.1 Liquid"),
    ("invalid/manifest_not_mapping", "reject", "reject", ""),
    ("invalid/missing_asset", "reject", "reject", ""),
    ("invalid/missing_content_id", "reject", "reject", ""),
    ("invalid/missing_date", "reject", "reject", ""),
    ("invalid/missing_front_matter", "reject", "reject", ""),
    ("invalid/nested_collections", "reject", "reject", ""),
    ("invalid/no_manifest", "reject", "reject", ""),
    ("invalid/root_collection_with_others", "reject", "reject", ""),
    ("invalid/unknown_key", "reject", "reject", ""),
    ("invalid/unknown_kind", "reject", "reject", ""),
    ("invalid/unknown_reference_kind", "reject", "reject", ""),
    ("invalid/unresolved_link", "reject", "reject", ""),
    ("invalid/unresolved_reference", "reject", "reject", ""),
    ("invalid/wiki_subdirectory", "reject", "reject", ""),
    ("invalid/wikilink", "reject", "accept", "4.1 wikilink"),
)


@pytest.mark.parametrize(
    ("name", "validator", "toolkit", "difference"), PARITY, ids=[entry[0] for entry in PARITY]
)
def test_the_toolkit_and_the_validator_agree_on_every_fixture(name, validator, toolkit, difference):
    checked = check_repository(FIXTURES / name)
    diagnostics = toolkit_diagnostics(FIXTURES / name)

    rendered = "\n".join(item.render() for item in checked)
    assert ("reject" if any(item.severity == "error" for item in checked) else "accept") == (
        validator
    ), rendered
    assert (
        "reject" if any(item.severity == "error" for item in diagnostics) else "accept"
    ) == toolkit, rendered
    assert bool(difference) == (validator != toolkit)


@pytest.mark.parametrize("name", [entry[0] for entry in PARITY])
def test_every_toolkit_diagnostic_is_a_validator_diagnostic(name):
    """One implementation: `check_content` adds diagnostics, it never drops one."""

    checked = check_repository(FIXTURES / name)

    diagnostics = toolkit_diagnostics(FIXTURES / name)

    missing = [item.render() for item in diagnostics if item not in checked]
    assert not missing, "\n".join(missing)


def test_the_parity_table_names_every_fixture():
    """A new fixture cannot escape the table that pins the boundary."""

    found = {
        str(path.relative_to(FIXTURES))
        for path in (*FIXTURES.iterdir(), *(FIXTURES / "invalid").iterdir())
        if path.is_dir() and path.name != "invalid"
    }

    assert found == {entry[0] for entry in PARITY}


def toolkit_diagnostics(path):
    """Both halves of the toolkit over one repository, as a parser runs them."""

    result = read_repository(path)
    return [*result.diagnostics, *resolve_repository(result).diagnostics]


def test_the_validator_reads_the_repository_through_the_toolkit(tmp_path):
    """The two never disagree about a reading rule, because there is one."""

    shutil.copytree(FIXTURES / "valid_multi", tmp_path / "repository")
    (tmp_path / "repository" / "wiki" / "a-b-testing.md").write_text(
        "---\ntitle: No identity\n---\n\nBody.\n"
    )

    checked = check_repository(tmp_path / "repository")
    diagnostics = toolkit_diagnostics(tmp_path / "repository")

    assert sorted(item.render() for item in diagnostics if item.severity == "error") == sorted(
        item.render() for item in checked if item.severity == "error"
    )


def test_a_directory_ignore_empties_is_invisible(tmp_path):
    """Section 3.1: `ignore` hides the directory, not only its files."""

    (tmp_path / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
        'ignore:\n  - "wiki/tools/**"\n'
    )
    (tmp_path / "wiki" / "tools").mkdir(parents=True)
    (tmp_path / "wiki" / "tools" / "build.py").write_text("x = 1\n")
    (tmp_path / "wiki" / "a.md").write_text(
        '---\ncontent_id: "88888888-8888-4888-8888-888888888888"\ntitle: A\n---\n\nBody.\n'
    )

    result = read_repository(tmp_path)

    assert result.ok
    assert [item.raw.path for item in result.documents] == ["wiki/a.md"]


def test_an_empty_collection_root_is_not_a_missing_directory(tmp_path):
    (tmp_path / "content.yaml").write_text(
        'schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\nignore:\n  - "wiki/**"\n'
    )
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "draft.md").write_text("no front matter\n")

    result = read_repository(tmp_path)

    assert result.ok
    assert result.documents == ()
