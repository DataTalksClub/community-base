import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from community_base.knowledge_base.models import (
    SECTION_DOCS,
    SECTION_WIKI,
    KnowledgeBasePage,
)

pytestmark = pytest.mark.django_db


def make_page(*, section=SECTION_DOCS, slug="page", title="Page", body="", parent=None, **fields):
    page = KnowledgeBasePage(
        section=section, slug=slug, title=title, body=body, parent=parent, **fields
    )
    page.full_clean()
    page.save()
    return page


def test_wiki_page_cannot_have_a_parent():
    parent = make_page(slug="parent", title="Parent")
    with pytest.raises(ValidationError) as error:
        make_page(section=SECTION_WIKI, slug="child", title="Child", parent=parent)
    assert "parent" in error.value.message_dict


def test_page_cannot_be_its_own_parent():
    page = make_page(slug="loop", title="Loop")
    page.parent = page
    with pytest.raises(ValidationError):
        page.full_clean()


def test_parent_must_belong_to_the_same_section():
    wiki_parent = make_page(section=SECTION_WIKI, slug="wiki-parent", title="Wiki parent")
    with pytest.raises(ValidationError) as error:
        make_page(slug="docs-child", title="Docs child", parent=wiki_parent)
    assert "parent" in error.value.message_dict


def test_slug_allows_dots_but_not_slashes():
    page = make_page(slug="install.cmd", title="Install")
    assert page.slug == "install.cmd"
    with pytest.raises(ValidationError):
        make_page(slug="no/slashes", title="No")


def test_body_html_is_rendered_and_sanitized_on_save():
    page = make_page(slug="intro", title="Intro", body="# Heading\n\n**bold** text")
    assert "<h1>Heading</h1>" in page.body_html
    assert "<strong>bold</strong>" in page.body_html


def test_leading_title_h1_is_stripped():
    page = make_page(slug="guide", title="Guide", body="# Guide\n\nBody text.")
    assert "<h1>" not in page.body_html
    assert "Body text." in page.body_html


def test_partial_provenance_is_rejected():
    page = KnowledgeBasePage(
        section=SECTION_DOCS, slug="half", title="Half", source_path="docs/half.md"
    )
    with pytest.raises(ValidationError):
        page.full_clean()


def test_section_slug_is_unique():
    make_page(section=SECTION_DOCS, slug="dup", title="First")
    duplicate = KnowledgeBasePage(section=SECTION_DOCS, slug="dup", title="Second")
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save()


def test_get_absolute_url_builds_the_documentation_path():
    index = make_page(slug="index", title="Documentation")
    setup = make_page(slug="setup", title="Setup", parent=index)
    assert index.get_absolute_url() == "/docs/index/"
    assert setup.get_absolute_url() == "/docs/index/setup/"


def test_wiki_absolute_url_is_flat():
    page = make_page(section=SECTION_WIKI, slug="faq", title="FAQ")
    assert page.get_absolute_url() == "/wiki/faq/"


def test_ancestor_slugs_run_from_the_root_down():
    index = make_page(slug="index", title="Documentation")
    mid = make_page(slug="mid", title="Mid", parent=index)
    leaf = make_page(slug="leaf", title="Leaf", parent=mid)
    assert leaf.ancestor_slugs() == ["index", "mid"]
    assert index.ancestor_slugs() == []
