import pytest

from community_base.knowledge_base import search
from community_base.knowledge_base.models import SECTION_WIKI, KnowledgeBasePage

pytestmark = pytest.mark.django_db


def make_page(*, section="docs", slug="page", title="Page", body="", **fields):
    page = KnowledgeBasePage(section=section, slug=slug, title=title, body=body, **fields)
    page.full_clean()
    page.save()
    return page


def test_corpus_covers_published_pages_of_both_sections():
    make_page(slug="docs-page", title="Docs page", body="reference material")
    make_page(section=SECTION_WIKI, slug="wiki-page", title="Wiki page")
    corpus = search.search_corpus()
    assert {(entry.section, entry.slug) for entry in corpus} == {
        ("docs", "docs-page"),
        ("wiki", "wiki-page"),
    }


def test_draft_pages_are_not_searchable():
    page = make_page(slug="hidden", title="Hidden", body="secret plan")
    KnowledgeBasePage.objects.filter(pk=page.pk).update(status="draft")
    assert search.search_pages("secret") == ()


def test_terms_are_anded_case_insensitively_across_title_summary_and_body():
    make_page(
        slug="billing-faq",
        title="Billing FAQ",
        summary="Refunds and invoices.",
        body="Contact support for help.",
    )
    assert [entry.slug for entry in search.search_pages("billing refunds")] == ["billing-faq"]
    assert [entry.slug for entry in search.search_pages("BILLING refunds")] == ["billing-faq"]
    assert search.search_pages("billing nonexistent") == ()


def test_haystack_is_plain_text_from_the_sanitized_html():
    make_page(slug="release", title="Release", body="Release & notes")
    assert [entry.slug for entry in search.search_pages("& notes")] == ["release"]


def test_section_filter_limits_the_corpus():
    make_page(slug="docs-one", title="Installer", body="setup steps")
    make_page(section=SECTION_WIKI, slug="wiki-one", title="Installer", body="setup steps")
    found = search.search_pages("setup", section=SECTION_WIKI)
    assert [entry.slug for entry in found] == ["wiki-one"]


def test_result_cap_cannot_be_exceeded_by_a_larger_limit():
    make_page(slug="one", title="One", body="shared token")
    make_page(slug="two", title="Two", body="shared token")
    assert len(search.search_pages("shared token", limit=1)) == 1
    assert len(search.search_pages("shared token", limit=5000)) == 2


def test_corpus_stamp_is_empty_then_moves_with_pages():
    assert search.corpus_stamp() == (0, "")
    page = make_page(slug="only", title="Only")
    total, latest = search.corpus_stamp()
    assert total == 1
    assert str(page.updated_at) == latest
