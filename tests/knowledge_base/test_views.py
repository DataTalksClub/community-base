import pytest
from django.test import Client

from community_base.knowledge_base import hierarchy
from community_base.knowledge_base.models import (
    SECTION_WIKI,
    STATUS_DRAFT,
    KnowledgeBasePage,
)

pytestmark = pytest.mark.django_db


def make_page(*, section="docs", slug="page", title="Page", body="", parent=None, nav_order=0):
    page = KnowledgeBasePage(
        section=section, slug=slug, title=title, body=body, parent=parent, nav_order=nav_order
    )
    page.full_clean()
    page.save()
    return page


def make_tree():
    index = make_page(slug="index", title="Documentation", body="Welcome.", nav_order=1)
    setup = make_page(
        slug="setup", title="Setup", body="Install the CLI.", parent=index, nav_order=10
    )
    advanced = make_page(
        slug="advanced",
        title="Advanced usage",
        body="Power-user flags.",
        parent=index,
        nav_order=20,
    )
    make_page(
        section=SECTION_WIKI, slug="billing-faq", title="Billing FAQ", body="**billing** help"
    )
    return index, setup, advanced


def test_wiki_home_lists_every_published_wiki_page():
    make_tree()
    response = Client().get("/wiki/")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'href="/wiki/billing-faq/"' in body
    assert "Billing FAQ" in body


def test_wiki_page_renders_the_stored_html():
    make_tree()
    response = Client().get("/wiki/billing-faq/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Billing FAQ" in body
    assert "<strong>billing</strong>" in body


def test_wiki_draft_page_is_404():
    page = make_page(section=SECTION_WIKI, slug="secret", title="Secret")
    KnowledgeBasePage.objects.filter(pk=page.pk).update(status=STATUS_DRAFT)
    assert Client().get("/wiki/secret/").status_code == 404


def test_docs_home_shows_the_nested_tree():
    make_tree()
    response = Client().get("/docs/")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'href="/docs/index/"' in body
    assert 'href="/docs/index/setup/"' in body
    assert 'href="/docs/index/advanced/"' in body


def test_nested_docs_page_renders_breadcrumbs_and_sequential_navigation():
    _index, setup, _advanced = make_tree()
    response = Client().get("/docs/index/setup/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Setup" in body
    assert 'href="/docs/index/"' in body
    assert 'href="/docs/index/advanced/"' in body
    assert hierarchy.breadcrumbs(setup) != ()


def test_unknown_docs_segment_is_404():
    make_tree()
    assert Client().get("/docs/index/nope/").status_code == 404
    assert Client().get("/docs/nope/").status_code == 404


def test_wiki_page_with_dotted_slug_is_served():
    make_page(section=SECTION_WIKI, slug="install.cmd", title="Install")
    response = Client().get("/wiki/install.cmd/")
    assert response.status_code == 200
