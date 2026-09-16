import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from community_base.knowledge_base.models import SECTION_WIKI, KnowledgeBasePage

pytestmark = pytest.mark.django_db


def make_page(*, section="docs", slug="page", title="Page", parent=None, nav_order=0, **fields):
    page = KnowledgeBasePage(
        section=section, slug=slug, title=title, parent=parent, nav_order=nav_order, **fields
    )
    page.full_clean()
    page.save()
    return page


def make_staff_client():
    user = get_user_model().objects.create_user(email="staffer@example.com", is_staff=True)
    client = Client()
    client.force_login(user)
    return client


def test_studio_list_requires_staff():
    user = get_user_model().objects.create_user(email="member@example.com")
    client = Client()
    client.force_login(user)
    response = client.get("/studio/knowledge-base/")
    assert response.status_code == 403


def test_studio_list_shows_pages_with_section_and_query_filters():
    make_page(slug="docs-page", title="Docs page")
    make_page(section=SECTION_WIKI, slug="wiki-page", title="Wiki page")
    client = make_staff_client()

    page = client.get("/studio/knowledge-base/")
    assert page.status_code == 200
    assert b"Docs page" in page.content
    assert b"Wiki page" in page.content

    wiki_only = client.get("/studio/knowledge-base/", {"section": SECTION_WIKI})
    assert b"Docs page" not in wiki_only.content
    assert b"Wiki page" in wiki_only.content

    search = client.get("/studio/knowledge-base/", {"q": "Docs"})
    assert b"Docs page" in search.content
    assert b"Wiki page" not in search.content


def test_studio_detail_shows_ancestors_and_children():
    index = make_page(slug="index", title="Documentation")
    setup = make_page(slug="setup", title="Setup", parent=index, nav_order=10)
    client = make_staff_client()

    detail = client.get(f"/studio/knowledge-base/{setup.pk}/")
    assert detail.status_code == 200
    assert b"Documentation" in detail.content

    parent_detail = client.get(f"/studio/knowledge-base/{index.pk}/")
    assert b"Setup" in parent_detail.content
