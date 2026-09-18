"""The document conversion of `C7.12`: what it rewrites, and what it refuses."""

from pathlib import Path

import pytest
import yaml

from community_base.content_sync.check import check_repository
from community_base.content_sync.convert.documents import (
    PROFILES,
    Collection,
    Profile,
    convert_documents,
)

WIKI = Profile(
    name="wiki-fixture",
    collections=(
        Collection(
            kind="wiki",
            source="_wiki",
            target="wiki",
            layout="flat",
            drop=("layout",),
            title_references=("related",),
            jekyll_urls=True,
            url_prefix="/course-wiki",
        ),
    ),
)

PAGE = """---
layout: wiki
title: "Vector Search"
summary: "Searching by meaning."
related:
  - Agentic RAG
topics:
  - search
---

# Vector Search

See [Agentic RAG](/course-wiki/agentic-rag/) and [[Agentic RAG]].
"""

OTHER = """---
layout: wiki
title: "Agentic RAG"
summary: "Retrieval the model drives."
---

A body.
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def repository(root: Path, **overrides: str) -> Path:
    files = {"_wiki/vector-search.md": PAGE, "_wiki/agentic-rag.md": OTHER}
    files.update(overrides)
    return write(root, files)


def front_matter(root: Path, name: str):
    return yaml.safe_load((root / name).read_text().split("---", 2)[1])


def paths(root: Path) -> list[str]:
    return sorted(item.relative_to(root).as_posix() for item in root.glob("**/*") if item.is_file())


# --- what it writes -----------------------------------------------------------


def test_a_page_moves_out_of_the_underscore_directory(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    assert "wiki/vector-search.md" in paths(root)
    assert "_wiki/vector-search.md" not in paths(root)


def test_the_manifest_declares_the_collections_of_the_profile(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    manifest = yaml.safe_load((root / "content.yaml").read_text())
    assert manifest["collections"] == [{"kind": "wiki", "path": "wiki"}]


def test_a_content_id_is_minted_once_and_stays(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)
    first = front_matter(root, "wiki/vector-search.md")["content_id"]
    convert_documents(root, WIKI)

    assert front_matter(root, "wiki/vector-search.md")["content_id"] == first


def test_a_title_reference_becomes_a_typed_reference(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    assert front_matter(root, "wiki/vector-search.md")["related"] == ["wiki:agentic-rag"]


def test_a_key_the_format_cannot_express_moves_under_extra(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    assert front_matter(root, "wiki/vector-search.md")["extra"] == {"topics": ["search"]}


def test_a_site_path_becomes_a_relative_file_link(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    assert "(agentic-rag.md)" in (root / "wiki/vector-search.md").read_text()


def test_a_wikilink_becomes_a_typed_link(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    assert "[Agentic RAG](wiki:agentic-rag)" in (root / "wiki/vector-search.md").read_text()


def test_a_kramdown_attribute_list_is_removed(tmp_path):
    root = repository(tmp_path, **{"_wiki/vector-search.md": PAGE + "\nStyled\n{: .fs-9 }\n"})

    convert_documents(root, WIKI)

    assert "{: .fs-9 }" not in (root / "wiki/vector-search.md").read_text()


# --- what it refuses ----------------------------------------------------------


@pytest.mark.parametrize(
    ("page", "rule"),
    [
        (PAGE.replace("Agentic RAG\n", "Nothing At All\n", 1), "3.7"),
        (PAGE + "\n```python\nunclosed\n", "4.1"),
        (PAGE + "\n{% include youtube.html %}\n", "4.1"),
    ],
)
def test_a_construct_it_does_not_understand_is_refused(tmp_path, page, rule):
    root = repository(tmp_path, **{"_wiki/vector-search.md": page})

    report = convert_documents(root, WIKI)

    assert [item.rule for item in report.refusals] == [rule]
    assert "_wiki/vector-search.md" in paths(root)


def test_a_name_that_is_not_a_slug_is_refused(tmp_path):
    root = repository(tmp_path, **{"_wiki/ella(wati).md": OTHER})

    report = convert_documents(root, WIKI)

    assert [item.rule for item in report.refusals] == ["3.4"]


def test_an_unterminated_fence_is_refused_rather_than_half_converted(tmp_path):
    root = repository(tmp_path, **{"_wiki/vector-search.md": PAGE + "\n```\nopen\n"})

    report = convert_documents(root, WIKI)

    assert "never closed" in report.refusals[0].message


# --- the two properties the issue asks for ------------------------------------


def test_the_conversion_accounts_for_every_file(tmp_path):
    root = repository(tmp_path, **{"images/cover.png": "bytes"})

    report = convert_documents(root, WIKI)

    assert report.verify() == []


def test_running_it_twice_produces_no_second_change(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)
    after = {path: (root / path).read_bytes() for path in paths(root)}
    second = convert_documents(root, WIKI)

    assert second.converted == 0
    assert {path: (root / path).read_bytes() for path in paths(root)} == after


def test_a_converted_repository_passes_the_validator(tmp_path):
    root = repository(tmp_path)

    convert_documents(root, WIKI)

    assert [item.render() for item in check_repository(root)] == []


def test_a_dry_run_writes_nothing(tmp_path):
    root = repository(tmp_path)
    before = {path: (root / path).read_bytes() for path in paths(root)}

    report = convert_documents(root, WIKI, apply=False)

    assert report.converted > 0
    assert {path: (root / path).read_bytes() for path in paths(root)} == before


def test_every_shipped_profile_names_a_registered_or_site_kind():
    """The profiles are the sixteen repositories; each names one kind per collection."""

    assert set(PROFILES) == {
        "aisl-wiki",
        "podwiki",
        "dtc-people",
        "dtc-articles",
        "dtc-docs",
        "faq",
    }
    for profile in PROFILES.values():
        for collection in profile.collections:
            assert collection.kind
            assert collection.layout in ("flat", "item", "tree", "data", "opaque")
