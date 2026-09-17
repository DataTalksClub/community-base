"""The opaque site record: one JSON object, no per-site columns (C7.4)."""

import pytest
from django.core.exceptions import ValidationError

from community_base.knowledge_base.models import (
    SECTION_DOCS,
    SECTION_WIKI,
    KnowledgeBasePage,
)
from tests.knowledge_base.fixture_parser import KbDocsTreeFixtureParser, KbFixtureParser
from tests.knowledge_base.utils import DOCS_TREE_REPO, KB_REPO, ParserHarness

pytestmark = pytest.mark.django_db

# The shapes the donor parsers produce today: DataTalks.Club wiki pages
# (content/sync_parsers/podwiki.py) and documentation records
# (content/docs_projection.py).
WIKI_RECORD = {
    "blocks": [
        {"kind": "heading", "id": "what-is-it", "text": "What is it"},
        {"kind": "paragraph", "text": "A wiki page body is blocks, not markdown."},
    ],
    "tags": ["podcast", "mlops"],
    "fragment_ids": ["what-is-it"],
    "unresolved_fragment_ids": [],
    "relations": [{"kind": "podcast", "path": "/podcast/s01e01/", "title": "Episode 1"}],
}
DOCS_RECORD = {
    "edit_url": "https://example.invalid/edit/docs/course-a/project.md",
    "has_toc": True,
    "has_children": False,
    "permalink": "/docs/course-a/project/",
    "grand_parent": "",
    "body_sha256": "a" * 64,
    "images": ["/docs/assets/diagram.png"],
}


def make_page(*, section=SECTION_DOCS, slug="page", title="Page", **fields):
    page = KnowledgeBasePage(section=section, slug=slug, title=title, **fields)
    page.full_clean()
    page.save()
    return page


def test_the_record_defaults_to_an_empty_object():
    page = make_page(slug="plain", title="Plain")
    page.refresh_from_db()
    assert page.record == {}


def test_the_wiki_record_round_trips():
    page = make_page(section=SECTION_WIKI, slug="mlops", title="MLOps", record=WIKI_RECORD)
    page.refresh_from_db()

    assert page.record == WIKI_RECORD
    assert page.record["blocks"][0]["id"] == "what-is-it"
    assert page.record["unresolved_fragment_ids"] == []


def test_the_docs_record_round_trips():
    page = make_page(slug="project", title="Project", record=DOCS_RECORD)
    page.refresh_from_db()

    assert page.record == DOCS_RECORD
    assert page.record["edit_url"].endswith("docs/course-a/project.md")


def test_a_record_that_is_not_an_object_is_refused():
    for bad in ([1, 2], "text", 7):
        with pytest.raises(ValidationError) as error:
            make_page(slug="bad", title="Bad", record=bad)
        assert "record" in error.value.message_dict


def test_the_tree_parser_stores_and_replaces_its_record():
    ParserHarness().run_parser(KbDocsTreeFixtureParser(), DOCS_TREE_REPO)

    page = KnowledgeBasePage.objects.get(source_path="docs/course-a/module-1/project.md")
    assert page.record["grand_parent"] == "course-a"
    assert page.record["fragment_ids"] == ["project-heading"]
    assert page.record["edit_url"].endswith("docs/course-a/module-1/project.md")


def test_a_parser_that_stores_no_record_leaves_it_empty():
    ParserHarness().run_parser(KbFixtureParser(), KB_REPO)

    for page in KnowledgeBasePage.objects.all():
        assert page.record == {}
