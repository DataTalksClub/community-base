"""A7.1 is live on this app: a page written the old way must not change.

Every capability C7.4 adds is opt-in. These tests pin the behaviour of a page
that opts into none of it -- the shape AI Shipping Labs runs in production off
tag v0.4.7 -- against the three places C7.4 touched: the key, the URL and the
rendering, and against the two C7.9c touched: the provenance fields and the
ownership scope of ``delete_missing``.
"""

import pytest

from community_base.content_sync.models import ContentSource
from community_base.curriculum.rendering import strip_leading_title_h1
from community_base.knowledge_base import hierarchy, sync
from community_base.knowledge_base.models import (
    BODY_HTML_MARKDOWN,
    SECTION_DOCS,
    SECTION_WIKI,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    KnowledgeBasePage,
)
from community_base.knowledge_base.rendering import render_markdown
from tests.knowledge_base.fixture_parser import KbFixtureParser
from tests.knowledge_base.utils import COMMIT_SHA, KB_REPO, ParserHarness, make_source

pytestmark = pytest.mark.django_db


def test_a_page_created_without_any_new_field_takes_the_old_defaults():
    page = KnowledgeBasePage.objects.create(
        section=SECTION_DOCS, slug="setup", title="Setup", body="**bold** text"
    )
    page.refresh_from_db()

    assert page.public_path is None
    assert page.record == {}
    assert page.body_html_source == BODY_HTML_MARKDOWN
    assert page.body_html == render_markdown("**bold** text")
    assert page.get_absolute_url() == "/docs/setup/"


def test_the_flat_parser_produces_exactly_what_it_produced_before():
    _source, _items, results, deleted = ParserHarness().run_parser(KbFixtureParser(), KB_REPO)

    assert [result.action for result in results] == ["created"] * 5
    assert deleted == []
    for page in KnowledgeBasePage.objects.all():
        assert page.public_path is None
        assert page.record == {}
        assert page.body_html_source == BODY_HTML_MARKDOWN
        assert page.body_html == render_markdown(strip_leading_title_h1(page.body, page.title))

    urls = {page.slug: page.get_absolute_url() for page in KnowledgeBasePage.objects.all()}
    assert urls == {
        "index": "/docs/index/",
        "setup": "/docs/index/setup/",
        "advanced": "/docs/index/advanced/",
        "getting-started": "/wiki/getting-started/",
        "billing-faq": "/wiki/billing-faq/",
    }


def test_the_flat_parser_still_resolves_a_parent_by_slug_alone():
    source = make_source()
    sync.upsert_page(
        source,
        section=SECTION_DOCS,
        slug="index",
        title="Documentation",
        commit_sha=COMMIT_SHA,
        source_path="docs/index.md",
        checksum="a" * 64,
    )
    page, action = sync.upsert_page(
        source,
        section=SECTION_DOCS,
        slug="setup",
        title="Setup",
        parent_slug="index",
        commit_sha=COMMIT_SHA,
        source_path="docs/setup.md",
        checksum="b" * 64,
    )

    assert action == "created"
    assert page.parent.slug == "index"
    assert page.get_absolute_url() == "/docs/index/setup/"


def test_delete_missing_still_takes_a_positional_set_of_slugs():
    source = make_source()
    for slug in ("kept", "gone"):
        sync.upsert_page(
            source,
            section=SECTION_WIKI,
            slug=slug,
            title=slug.title(),
            commit_sha=COMMIT_SHA,
            source_path=f"wiki/{slug}.md",
            checksum=("c" if slug == "kept" else "d") * 64,
        )

    drafted = sync.delete_missing(source, SECTION_WIKI, {"kept"})

    assert [page.slug for page in drafted] == ["gone"]
    assert KnowledgeBasePage.objects.get(slug="gone").status == STATUS_DRAFT
    assert KnowledgeBasePage.objects.get(slug="kept").status != STATUS_DRAFT


def test_drafting_a_page_does_not_disturb_its_rendered_body():
    page = KnowledgeBasePage.objects.create(
        section=SECTION_DOCS, slug="setup", title="Setup", body="**bold** text"
    )
    before = page.body_html

    page.status = STATUS_DRAFT
    page.save(update_fields=["status", "updated_at"])
    page.refresh_from_db()

    assert page.body_html == before


def test_the_navigation_tree_of_a_unique_slug_section_is_unchanged():
    ParserHarness().run_parser(KbFixtureParser(), KB_REPO)

    tree = hierarchy.navigation_tree()
    assert [item.slug for item in tree.roots] == ["index"]
    assert [item.slug for item in tree.preorder] == ["index", "setup", "advanced"]
    assert set(tree.by_slug) == {"index", "setup", "advanced"}
    setup = KnowledgeBasePage.objects.get(slug="setup")
    previous, following = hierarchy.sequential_navigation(setup)
    assert (previous.slug, following.slug) == ("index", "advanced")


def test_a_site_parser_that_passes_no_content_id_leaves_the_field_empty():
    """The A7.1 shape: provenance without an item ``content_id`` (C7.9c)."""

    source, _items, _results, _deleted = ParserHarness().run_parser(KbFixtureParser(), KB_REPO)

    for page in KnowledgeBasePage.objects.all():
        assert page.source_content_id is None
        assert page.source_id == source.pk
        assert page.source_path
        assert page.source_checksum


def test_delete_missing_scopes_by_the_source_foreign_key_not_by_the_uuid():
    first = make_source()
    second = ContentSource.objects.create(
        slug="second-source", repo_name="example/second", webhook_secret="secret-not-used-here"
    )
    for source, slug in ((first, "first-page"), (second, "second-page")):
        sync.upsert_page(
            source,
            section=SECTION_WIKI,
            slug=slug,
            title=slug.title(),
            commit_sha=COMMIT_SHA,
            source_path=f"wiki/{slug}.md",
            checksum=("e" if slug == "first-page" else "f") * 64,
        )

    drafted = sync.delete_missing(first, SECTION_WIKI, set())

    assert [page.slug for page in drafted] == ["first-page"]
    assert KnowledgeBasePage.objects.get(slug="second-page").status == STATUS_PUBLISHED


def test_a_studio_authored_page_is_never_drafted_by_a_sync():
    source = make_source()
    KnowledgeBasePage.objects.create(section=SECTION_WIKI, slug="hand-written", title="By hand")

    drafted = sync.delete_missing(source, SECTION_WIKI, set())

    assert drafted == []
    assert KnowledgeBasePage.objects.get(slug="hand-written").status == STATUS_PUBLISHED
