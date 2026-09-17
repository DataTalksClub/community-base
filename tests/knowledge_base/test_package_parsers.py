"""The package parsers for the `wiki`, `docs` and `person` kinds (C7.9c, D24).

The parsers are thin: the toolkit reads, resolves, renders and sanitizes, and
these tests pin what reaches the models -- the rendered HTML, the heading list,
the resolved reference list, the tree a docs collection makes, and the two
provenance fields that used to be one.
"""

import shutil

import pytest

from community_base.content_sync.media import MediaResult
from community_base.content_sync.models import ContentSource
from community_base.knowledge_base import routes
from community_base.knowledge_base.content_sync_parsers import (
    DocsParser,
    KnowledgeBaseParseError,
    PersonParser,
    WikiParser,
)
from community_base.knowledge_base.models import (
    BODY_HTML_SITE,
    SECTION_DOCS,
    SECTION_WIKI,
    STATUS_DRAFT,
    STATUS_PUBLISHED,
    KnowledgeBasePage,
    Person,
)
from tests.knowledge_base.utils import (
    ARTICLE_REPO,
    COMMIT_SHA,
    FORMAT_REPO,
    checkout,
    make_source,
    run_package_parsers,
)

pytestmark = pytest.mark.django_db


class FakeStore:
    """A media store that records what it was asked to upload."""

    def __init__(self):
        self.uploads = []

    def upload(self, active, path, source):
        active.read_bytes(path)
        self.uploads.append(path)
        return MediaResult(path, f"/media/{path}")


# --- the wiki kind ------------------------------------------------------------


def test_a_wiki_page_stores_the_rendered_html_the_headings_and_the_references():
    source = make_source()

    run_package_parsers(FORMAT_REPO, source)

    page = KnowledgeBasePage.objects.get(section=SECTION_WIKI, slug="a-b-testing")
    assert page.title == "A/B Testing"
    assert page.body_html_source == BODY_HTML_SITE
    assert '<h2 id="running-one">Running one</h2>' in page.body_html
    assert [heading["id"] for heading in page.record["headings"]] == [
        "running-one",
        "before-you-start",
    ]
    assert page.record["references"] == [
        {"kind": "wiki", "target": "power-analysis", "label": "", "href": "/wiki/power-analysis/"},
        {
            "kind": "wiki",
            "target": "power-analysis",
            "label": "power analysis",
            "href": "/wiki/power-analysis/",
        },
        {
            "kind": "person",
            "target": "alexey-grigorev",
            "label": "Alexey",
            "href": "/people/alexey-grigorev/",
        },
    ]
    assert page.record["assets"] == ["wiki/images/chart.png"]
    assert page.record["values"]["page_type"] == "concept"
    assert page.record["values"]["extra"] == {"keyword": "ab testing"}
    assert page.public_path == "/wiki/a-b-testing/"
    assert page.get_absolute_url() == "/wiki/a-b-testing/"


def test_a_wiki_page_carries_the_asset_url_the_media_store_returned():
    store = FakeStore()

    run_package_parsers(FORMAT_REPO, make_source(), media=store)

    page = KnowledgeBasePage.objects.get(section=SECTION_WIKI, slug="a-b-testing")
    assert store.uploads.count("wiki/images/chart.png") == 1
    assert "/media/wiki/images/chart.png" in page.body_html
    assert page.record["values"]["image"] == "/media/wiki/images/chart.png"


def test_a_wiki_page_takes_its_sibling_order_from_the_front_matter():
    run_package_parsers(FORMAT_REPO, make_source())

    orders = {
        page.slug: page.nav_order for page in KnowledgeBasePage.objects.filter(section=SECTION_WIKI)
    }
    assert orders == {"a-b-testing": 0, "power-analysis": 2}


# --- the docs kind ------------------------------------------------------------


def test_a_three_level_docs_tree_round_trips_with_repeated_leaf_slugs():
    run_package_parsers(FORMAT_REPO, make_source())

    paths = {
        page.get_absolute_url(): page.title
        for page in KnowledgeBasePage.objects.filter(section=SECTION_DOCS)
    }
    assert paths == {
        "/docs/": "Documentation",
        "/docs/general/": "General",
        "/docs/general/joining/": "Joining the community",
        "/docs/courses/": "Courses",
        "/docs/courses/llm-zoomcamp/": "LLM Zoomcamp",
        "/docs/courses/llm-zoomcamp/joining/": "Joining the course",
    }
    repeated = KnowledgeBasePage.objects.filter(section=SECTION_DOCS, slug="joining")
    assert repeated.count() == 2
    assert {page.parent.slug for page in repeated} == {"general", "llm-zoomcamp"}


def test_each_docs_page_reads_back_at_its_own_path_through_the_shipped_route(client):
    run_package_parsers(FORMAT_REPO, make_source())

    for path, title in (
        ("/docs/general/joining/", "Joining the community"),
        ("/docs/courses/llm-zoomcamp/joining/", "Joining the course"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.context["page"].title == title


def test_a_docs_page_resolves_a_relative_link_to_the_other_repeated_leaf():
    run_package_parsers(FORMAT_REPO, make_source())

    page = KnowledgeBasePage.objects.get(
        section=SECTION_DOCS, slug="joining", parent__slug="llm-zoomcamp"
    )
    assert page.record["references"] == [
        {
            "kind": "docs",
            "target": "general/joining",
            "label": "general page",
            "href": "/docs/general/joining/",
        }
    ]
    assert 'href="/docs/general/joining/"' in page.body_html


# --- the person kind ----------------------------------------------------------


def test_a_person_is_stored_with_the_display_name_bio_picture_and_links():
    store = FakeStore()

    run_package_parsers(FORMAT_REPO, make_source(), media=store)

    person = Person.objects.get(slug="alexey-grigorev")
    assert person.title == "Alexey Grigorev"
    assert person.summary == "Engineer and instructor."
    assert person.image == "/media/people/images/alexey-grigorev.png"
    assert person.links == [{"label": "linkedin", "url": "https://www.linkedin.com/in/agrigorev/"}]
    assert "Alexey teaches the zoomcamps." in person.body_html
    assert person.get_absolute_url() == "/people/alexey-grigorev/"


def test_an_authors_reference_from_a_second_source_resolves_to_the_person():
    from community_base.content_sync.documents import read_repository
    from community_base.content_sync.resolution import resolve_repository

    run_package_parsers(FORMAT_REPO, make_source())

    with checkout(ARTICLE_REPO) as active:
        read = read_repository(active)
        resolved = resolve_repository(read, routes=routes.route_resolver(["article"])).by_path()[
            "articles/crisp-dm-for-ai/index.md"
        ]

    assert resolved.reference_records() == [
        {
            "kind": "person",
            "target": "alexey-grigorev",
            "label": "",
            "href": "/people/alexey-grigorev/",
        }
    ]


def test_an_authors_reference_is_unresolved_when_no_person_was_synced():
    from community_base.content_sync.documents import read_repository
    from community_base.content_sync.resolution import resolve_repository

    with checkout(ARTICLE_REPO) as active:
        result = resolve_repository(
            read_repository(active), routes=routes.route_resolver(["article"])
        )

    assert not result.ok
    assert "unresolved reference" in result.errors[0].message


# --- provenance ---------------------------------------------------------------


def test_a_synced_row_holds_the_item_content_id_and_names_its_source():
    source = make_source()

    run_package_parsers(FORMAT_REPO, source)

    page = KnowledgeBasePage.objects.get(section=SECTION_WIKI, slug="a-b-testing")
    person = Person.objects.get(slug="alexey-grigorev")
    assert str(page.source_content_id) == "c4d5e6f7-a8b9-4c0d-8e1f-2a3b4c5d6e7f"
    assert str(person.source_content_id) == "d7e8f9a0-b1c2-4d3e-8f4a-5b6c7d8e9f0a"
    assert page.source_id == source.pk
    assert page.source.repo_name == source.repo_name
    assert person.source_id == source.pk
    assert page.source_content_id != source.pk
    assert page.source_commit_sha == COMMIT_SHA


def test_a_second_run_of_the_same_commit_changes_nothing():
    source = make_source()
    run_package_parsers(FORMAT_REPO, source)

    outcome = run_package_parsers(FORMAT_REPO, source)

    actions = {
        kind: sorted({result.action for result in results})
        for kind, (_items, results, _drafted) in outcome.items()
    }
    assert actions == {"wiki": ["unchanged"], "docs": ["unchanged"], "person": ["unchanged"]}


# --- soft deletion ------------------------------------------------------------


def test_a_removed_page_is_drafted_through_the_source_foreign_key(tmp_path):
    source = make_source()
    copy = tmp_path / "repo"
    shutil.copytree(FORMAT_REPO, copy)
    run_package_parsers(copy, source)

    (copy / "wiki" / "power-analysis.md").unlink()
    (copy / "wiki" / "a-b-testing.md").write_text(
        (copy / "wiki" / "a-b-testing.md")
        .read_text()
        .replace("related: [wiki:power-analysis]\n", "")
        .replace("Do the [power analysis](wiki:power-analysis) first, with", "Work with")
    )
    outcome = run_package_parsers(copy, source)

    assert [page.slug for page in outcome["wiki"][2]] == ["power-analysis"]
    assert KnowledgeBasePage.objects.get(slug="power-analysis").status == STATUS_DRAFT
    assert KnowledgeBasePage.objects.get(slug="a-b-testing").status == STATUS_PUBLISHED


def test_another_sources_pages_are_never_drafted(tmp_path):
    first = make_source()
    second = ContentSource.objects.create(
        slug="second", repo_name="example/second", webhook_secret="secret-not-used-here"
    )
    run_package_parsers(FORMAT_REPO, first)
    empty = tmp_path / "empty"
    (empty / "wiki").mkdir(parents=True)
    (empty / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
    )

    outcome = run_package_parsers(empty, second)

    assert outcome["wiki"][2] == []
    assert KnowledgeBasePage.objects.filter(status=STATUS_DRAFT).count() == 0


def test_a_repository_that_declares_none_of_these_kinds_drafts_nothing():
    source = make_source()
    run_package_parsers(FORMAT_REPO, source)

    outcome = run_package_parsers(ARTICLE_REPO, source)

    assert [(kind, items) for kind, (items, _r, _d) in outcome.items()] == [
        ("person", []),
        ("docs", []),
        ("wiki", []),
    ]
    assert all(drafted == [] for _items, _results, drafted in outcome.values())
    assert KnowledgeBasePage.objects.filter(status=STATUS_DRAFT).count() == 0
    assert Person.objects.filter(status=STATUS_DRAFT).count() == 0


def test_a_repository_with_no_manifest_is_not_this_parsers(tmp_path):
    empty = tmp_path / "plain"
    (empty / "wiki").mkdir(parents=True)
    (empty / "wiki" / "a-page.md").write_text("no front matter here\n")

    outcome = run_package_parsers(empty, make_source())

    assert all(items == [] for items, _results, _drafted in outcome.values())


def test_a_declared_collection_that_cannot_be_read_is_an_error(tmp_path):
    broken = tmp_path / "broken"
    (broken / "wiki").mkdir(parents=True)
    (broken / "content.yaml").write_text(
        "schema_version: 1\ncollections:\n  - kind: wiki\n    path: wiki\n"
    )
    (broken / "wiki" / "a-page.md").write_text("---\ntitle: No identity\n---\n\nBody.\n")

    with checkout(broken) as active, pytest.raises(KnowledgeBaseParseError) as error:
        WikiParser().discover(active, make_source())

    assert "content_id" in str(error.value)


# --- one read per checkout ----------------------------------------------------


def test_the_three_parsers_share_one_read_and_one_resolution():
    store = FakeStore()
    source = make_source()

    with checkout(FORMAT_REPO) as active:
        views = []
        for parser in (PersonParser(), DocsParser(), WikiParser()):
            items = list(parser.discover(active, source))
            for item in items:
                parser.upsert(item, source, store)
            views.append(parser._view)

    assert views[0] is views[1] is views[2]
    # Every asset is uploaded once for the repository, not once per parser.
    assert sorted(store.uploads) == [
        "people/images/alexey-grigorev.png",
        "wiki/images/chart.png",
    ]
