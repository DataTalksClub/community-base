import shutil

import pytest

from community_base.knowledge_base import hierarchy, sync
from community_base.knowledge_base.models import (
    SECTION_DOCS,
    SECTION_WIKI,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    KnowledgeBasePage,
)
from tests.knowledge_base.fixture_parser import KbFixtureParser
from tests.knowledge_base.utils import COMMIT_SHA, KB_REPO, ParserHarness, make_source

pytestmark = pytest.mark.django_db


def test_fixture_parser_builds_a_two_level_docs_tree_and_a_flat_wiki_set():
    _source, items, results, deleted = ParserHarness().run_parser(KbFixtureParser(), KB_REPO)

    assert deleted == []
    assert [result.action for result in results] == ["created"] * 5
    assert {item.key for item in items} == {
        "wiki:getting-started",
        "wiki:billing-faq",
        "docs:index",
        "docs:setup",
        "docs:advanced",
    }

    tree = hierarchy.navigation_tree()
    assert [item.slug for item in tree.roots] == ["index"]
    assert [child.slug for child in tree.roots[0].children] == ["setup", "advanced"]
    assert [page.slug for page in hierarchy.wiki_pages()] == [
        "getting-started",
        "billing-faq",
    ]


def test_reimport_is_unchanged():
    harness = ParserHarness()
    harness.run_parser(KbFixtureParser(), KB_REPO)

    _source, _items, results, deleted = harness.run_parser(KbFixtureParser(), KB_REPO)

    assert [result.action for result in results] == ["unchanged"] * 5
    assert deleted == []
    assert KnowledgeBasePage.objects.count() == 5


def test_body_change_updates_the_page(tmp_path):
    repo = shutil.copytree(KB_REPO, tmp_path / "repo")
    harness = ParserHarness()
    harness.run_parser(KbFixtureParser(), repo)
    (repo / "docs" / "setup.md").write_text(
        "---\ntitle: Setup\nparent: index\nnav_order: 10\n---\n\nNew instructions.\n"
    )

    _source, _items, results, _deleted = harness.run_parser(KbFixtureParser(), repo)

    actions = {result.obj.slug: result.action for result in results}
    assert actions["setup"] == "updated"
    page = KnowledgeBasePage.objects.get(section=SECTION_DOCS, slug="setup")
    assert "New instructions." in page.body_html


def test_vanished_page_is_drafted_not_deleted(tmp_path):
    repo = shutil.copytree(KB_REPO, tmp_path / "repo")
    harness = ParserHarness()
    harness.run_parser(KbFixtureParser(), repo)
    (repo / "docs" / "advanced.md").unlink()

    _source, _items, _results, deleted = harness.run_parser(KbFixtureParser(), repo)

    assert [page.slug for page in deleted] == ["advanced"]
    page = KnowledgeBasePage.objects.get(section=SECTION_DOCS, slug="advanced")
    assert page.status == STATUS_DRAFT


def test_parent_must_exist_before_the_child():
    source = make_source()
    with pytest.raises(sync.KnowledgeBaseSyncError):
        sync.upsert_page(
            source,
            section=SECTION_DOCS,
            slug="orphan",
            title="Orphan",
            parent_slug="missing-parent",
            commit_sha=COMMIT_SHA,
            source_path="docs/orphan.md",
            checksum="a" * 64,
        )


def test_wiki_page_cannot_sync_with_a_parent():
    source = make_source()
    with pytest.raises(sync.KnowledgeBaseSyncError):
        sync.upsert_page(
            source,
            section=SECTION_WIKI,
            slug="child",
            title="Child",
            parent_slug="anyone",
            commit_sha=COMMIT_SHA,
            source_path="wiki/child.md",
            checksum="a" * 64,
        )


def test_unknown_section_is_refused():
    source = make_source()
    with pytest.raises(sync.KnowledgeBaseSyncError):
        sync.upsert_page(
            source,
            section="blog",
            slug="post",
            title="Post",
            commit_sha=COMMIT_SHA,
            source_path="blog/post.md",
            checksum="a" * 64,
        )


def test_empty_commit_gets_a_stable_derived_commit():
    source = make_source()
    page, action = sync.upsert_page(
        source,
        section=SECTION_DOCS,
        slug="raw",
        title="Raw",
        commit_sha="",
        source_path="docs/raw.md",
        checksum="a" * 64,
    )
    assert action == "created"
    assert len(page.source_commit_sha) == 40

    again, action = sync.upsert_page(
        source,
        section=SECTION_DOCS,
        slug="raw",
        title="Raw",
        commit_sha="",
        source_path="docs/raw.md",
        checksum="a" * 64,
    )
    assert action == "unchanged"
    assert again.pk == page.pk


def test_delete_missing_is_scoped_to_one_source_and_skips_studio_rows():
    harness = ParserHarness()
    source, _items, _results, _deleted = harness.run_parser(KbFixtureParser(), KB_REPO)
    other = make_source(slug="other-source", repo="example/other")
    studio_page = KnowledgeBasePage(section=SECTION_DOCS, slug="studio-page", title="Studio")
    studio_page.full_clean()
    studio_page.save()

    drafted = sync.delete_missing(other, SECTION_DOCS, set())

    assert drafted == []
    assert KnowledgeBasePage.objects.filter(
        section=SECTION_DOCS, slug="studio-page", status=STATUS_PUBLISHED
    ).exists()

    synced_only = sync.delete_missing(source, SECTION_DOCS, {"index", "setup"})
    assert [page.slug for page in synced_only] == ["advanced"]
