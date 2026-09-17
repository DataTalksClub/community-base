"""Site-owned rendering: supplied HTML is sanitized, stored and preserved (C7.4)."""

import pytest

from community_base.knowledge_base.models import (
    BODY_HTML_MARKDOWN,
    BODY_HTML_SITE,
    SECTION_DOCS,
    KnowledgeBasePage,
)
from tests.knowledge_base.fixture_parser import KbDocsTreeFixtureParser
from tests.knowledge_base.utils import DOCS_TREE_REPO, ParserHarness

pytestmark = pytest.mark.django_db

SITE_HTML = '<div class="site-rendered"><h2 id="intro-heading">Intro</h2><p>Body.</p></div>'


def make_page(*, slug="page", title="Page", body="", **fields):
    page = KnowledgeBasePage(section=SECTION_DOCS, slug=slug, title=title, body=body, **fields)
    page.full_clean()
    page.save()
    return page


def test_a_page_renders_its_markdown_by_default():
    page = make_page(slug="intro", title="Intro", body="**bold** text")

    assert page.body_html_source == BODY_HTML_MARKDOWN
    assert "<strong>bold</strong>" in page.body_html


def test_supplied_html_replaces_the_markdown_rendering():
    page = make_page(slug="intro", title="Intro", body="**bold** text")
    page.set_site_rendered_html(SITE_HTML)
    page.save()
    page.refresh_from_db()

    assert page.body_html_source == BODY_HTML_SITE
    assert page.body_html == SITE_HTML
    assert "<strong>bold</strong>" not in page.body_html


def test_supplied_html_survives_a_further_save_untouched():
    page = make_page(slug="intro", title="Intro", body="**bold** text")
    page.set_site_rendered_html(SITE_HTML)
    page.save()

    stored = KnowledgeBasePage.objects.get(pk=page.pk)
    stored.title = "Intro, renamed"
    stored.save()
    stored.refresh_from_db()

    assert stored.body_html == SITE_HTML


def test_supplied_html_is_not_trusted():
    page = make_page(slug="intro", title="Intro")
    page.set_site_rendered_html(
        '<p onclick="steal()">Text</p><script>alert(1)</script>'
        '<a href="javascript:alert(1)">link</a>'
    )
    page.save()
    page.refresh_from_db()

    assert "<script>" not in page.body_html
    assert "onclick" not in page.body_html
    assert "javascript:" not in page.body_html
    assert "Text" in page.body_html


def test_a_page_can_be_handed_back_to_the_app_renderer():
    page = make_page(slug="intro", title="Intro", body="**bold** text")
    page.set_site_rendered_html(SITE_HTML)
    page.save()

    page.body_html_source = BODY_HTML_MARKDOWN
    page.save()
    page.refresh_from_db()

    assert "<strong>bold</strong>" in page.body_html


def test_the_tree_parser_stores_its_own_rendering():
    ParserHarness().run_parser(KbDocsTreeFixtureParser(), DOCS_TREE_REPO)

    page = KnowledgeBasePage.objects.get(source_path="docs/course-a/module-1/project.md")
    assert page.body_html_source == BODY_HTML_SITE
    assert page.body_html == (
        '<div class="site-rendered"><h2 id="project-heading">Module 1 project</h2>'
        "<p>The module 1 project brief.</p></div>"
    )

    page.save()
    page.refresh_from_db()
    assert page.body_html == (
        '<div class="site-rendered"><h2 id="project-heading">Module 1 project</h2>'
        "<p>The module 1 project brief.</p></div>"
    )


def test_a_parser_that_supplies_no_html_keeps_the_app_rendering():
    from tests.knowledge_base.fixture_parser import KbFixtureParser
    from tests.knowledge_base.utils import KB_REPO

    ParserHarness().run_parser(KbFixtureParser(), KB_REPO)

    for page in KnowledgeBasePage.objects.all():
        assert page.body_html_source == BODY_HTML_MARKDOWN
        assert page.public_path is None
