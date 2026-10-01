"""Site projection contracts for the package-owned wiki/docs lifecycle."""

from unittest.mock import patch

import pytest

from community_base.content_sync.models import SyncStatus
from community_base.content_sync.orchestration import sync_content_source
from community_base.knowledge_base.content_sync_parsers import DocsParser, WikiParser
from community_base.knowledge_base.models import (
    BODY_HTML_SITE,
    SECTION_DOCS,
    SECTION_WIKI,
    KnowledgeBasePage,
)
from community_base.knowledge_base.page_adaptation import page_site_adapter
from tests.knowledge_base.page_site_fixtures import (
    CHILD_ID,
    DOCS_ID,
    LEAF_ID,
    WIKI_ID,
    RecordingPageAdapter,
    document,
    package_page_parsers,
    write_repository,
)
from tests.knowledge_base.utils import checkout, make_source

pytestmark = pytest.mark.django_db


def run_parser(parser, repository, source):
    with checkout(repository) as active:
        items = list(parser.discover(active, source))
        results = [parser.upsert(item, source, None) for item in items]
        deleted = parser.soft_delete_missing({item.key for item in items}, source)
    return items, results, list(deleted)


def page_ids():
    return list(KnowledgeBasePage.objects.filter(section=SECTION_DOCS).values_list("pk", flat=True))


def assert_projected_tree():
    root = KnowledgeBasePage.objects.get(section=SECTION_DOCS, slug="docs")
    guide = KnowledgeBasePage.objects.get(section=SECTION_DOCS, slug="guide")
    child = KnowledgeBasePage.objects.get(section=SECTION_DOCS, slug="child")
    assert root.body_html_source == BODY_HTML_SITE
    assert root.public_path == "/projected/docs/docs/"
    assert root.record["projected"] == SECTION_DOCS
    assert guide.parent is None
    assert child.parent == guide


def test_projection_preserves_tree_identity_and_repeats_unchanged(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {
            "docs/index.md": document(DOCS_ID, "Docs"),
            "docs/01-guide/index.md": document(CHILD_ID, "Guide"),
            "docs/01-guide/01-child.md": document(LEAF_ID, "Child"),
        },
    )
    source = make_source()
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter):
        first = run_parser(DocsParser(), repository, source)
        identities = page_ids()
        second = run_parser(DocsParser(), repository, source)

    assert_projected_tree()
    assert page_ids() == identities
    assert [result.action for result in first[1]] == ["created", "created", "created"]
    assert [result.action for result in second[1]] == ["unchanged", "unchanged", "unchanged"]
    assert adapter.reports[-1].counts.unchanged == 3
    assert adapter.reports[-1].errors == ()


def test_real_orchestration_publishes_one_final_report_per_declared_section(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/page.md": document(WIKI_ID, "Page"),
            "docs/index.md": document(DOCS_ID, "Docs"),
        },
    )
    source = make_source()
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter), package_page_parsers():
        log = sync_content_source(source, repo_dir=repository)

    assert log.status == SyncStatus.SUCCESS
    assert {report.section for report in adapter.reports} == {SECTION_DOCS, SECTION_WIKI}
    assert sum(report.counts.created for report in adapter.reports) == 2
    assert all(report.completed for report in adapter.reports)
    assert all(not report.cleanup_suppressed for report in adapter.reports)


def test_identity_mutation_is_refused_before_storage(tmp_path):
    repository = write_repository(tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page")})
    source = make_source()
    adapter = RecordingPageAdapter()
    adapter.mutate_identity = True

    with (
        page_site_adapter(adapter),
        patch("community_base.knowledge_base.sync.upsert_page") as upsert,
    ):
        with pytest.raises(Exception, match="finished with 1 error"):
            run_parser(WikiParser(), repository, source)

    upsert.assert_not_called()
    assert adapter.reports[0].errors[0].step == "page_projection"
    assert adapter.tracebacks[0] is not None
