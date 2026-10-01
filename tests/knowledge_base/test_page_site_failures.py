"""Failure, cleanup and reporting boundaries for package-owned pages."""

import hashlib

import pytest

from community_base.content_sync.models import SyncStatus
from community_base.content_sync.orchestration import sync_content_source
from community_base.knowledge_base.content_sync_parsers import (
    DocsParser,
    KnowledgeBaseParseError,
    WikiParser,
)
from community_base.knowledge_base.models import (
    SECTION_DOCS,
    SECTION_WIKI,
    STATUS_DRAFT,
    KnowledgeBasePage,
)
from community_base.knowledge_base.page_adaptation import page_site_adapter
from community_base.knowledge_base.sync import upsert_page
from tests.knowledge_base.page_site_fixtures import (
    SECOND_WIKI_ID,
    WIKI_ID,
    RecordingPageAdapter,
    collections_manifest,
    document,
    package_page_parsers,
    write_repository,
)
from tests.knowledge_base.test_page_site_adapter import run_parser
from tests.knowledge_base.utils import COMMIT_SHA, make_source

pytestmark = pytest.mark.django_db


def old_page(source, slug, path):
    return upsert_page(
        source,
        section=SECTION_WIKI,
        slug=slug,
        title=slug.title(),
        commit_sha=COMMIT_SHA,
        source_path=path,
        checksum=hashlib.sha256(f"old:{slug}".encode()).hexdigest(),
    )[0]


def assert_boundary_result(adapter, log):
    assert log.status == SyncStatus.PARTIAL
    assert len(adapter.reports) == 1
    report = adapter.reports[0]
    assert not report.completed
    assert report.counts.created == 1
    assert [detail.key for detail in report.details] == ["wiki/01-first.md"]
    assert report.errors[0].record == {
        "file": "wiki/02-boundary.md",
        "error": "wiki/02-boundary.md: outside_checkout",
        "step": "filesystem_boundary",
        "kind": "outside_checkout",
        "filesystem_boundary": True,
        "retryable": False,
    }
    assert adapter.tracebacks[0] is not None
    assert "private-canary" not in repr(report)
    assert log.errors[0]["content_type"] == "knowledge_base_wiki"


def test_ordinary_failure_retains_failed_row_and_drafts_unrelated_missing_page(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/01-bad.md": document(WIKI_ID, "Bad"),
            "wiki/02-good.md": document(SECOND_WIKI_ID, "Good"),
        },
    )
    source = make_source()
    failed = old_page(source, "bad", "wiki/01-bad.md")
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()
    adapter.fail_path = "wiki/01-bad.md"

    with page_site_adapter(adapter), pytest.raises(Exception, match="finished with 1 error"):
        run_parser(WikiParser(), repository, source)

    failed.refresh_from_db()
    missing.refresh_from_db()
    assert failed.status != STATUS_DRAFT
    assert missing.status == STATUS_DRAFT
    assert KnowledgeBasePage.objects.filter(slug="good").exists()
    assert adapter.reports[0].counts.created == 1
    assert adapter.reports[0].counts.deleted == 1
    assert not adapter.reports[0].cleanup_suppressed
    assert adapter.tracebacks[0] is not None
    assert "private-canary" not in repr(adapter.reports[0])


def test_same_kind_read_diagnostic_keeps_valid_sibling_and_suppresses_cleanup(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/01-bad.md": "---\ntitle: Missing identity\n---\n\nBad.\n",
            "wiki/02-good.md": document(SECOND_WIKI_ID, "Good"),
        },
    )
    source = make_source()
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter), pytest.raises(Exception, match="finished with 1 error"):
        run_parser(WikiParser(), repository, source)

    missing.refresh_from_db()
    assert missing.status != STATUS_DRAFT
    assert KnowledgeBasePage.objects.filter(slug="good").exists()
    report = adapter.reports[0]
    assert report.cleanup_suppressed
    assert report.errors[0].source_path == "wiki/01-bad.md"


def test_other_page_kind_diagnostic_does_not_suppress_wiki_cleanup(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/good.md": document(WIKI_ID, "Good"),
            "docs/bad.md": "---\ntitle: Missing identity\n---\n\nBad.\n",
        },
    )
    source = make_source()
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter):
        run_parser(WikiParser(), repository, source)

    missing.refresh_from_db()
    assert missing.status == STATUS_DRAFT
    assert adapter.reports[0].errors == ()
    assert not adapter.reports[0].cleanup_suppressed


def test_missing_image_is_stored_reported_and_cleanup_remains_safe(tmp_path):
    body = "![Missing](images/not-there.png)"
    repository = write_repository(
        tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page", body)}
    )
    source = make_source()
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter), pytest.raises(Exception, match="finished with 1 error"):
        run_parser(WikiParser(), repository, source)

    missing.refresh_from_db()
    assert missing.status == STATUS_DRAFT
    assert KnowledgeBasePage.objects.filter(slug="page").exists()
    report = adapter.reports[0]
    assert report.errors[0].step == "image_reference_missing"
    assert report.counts.created == 1
    assert report.counts.deleted == 1
    assert not report.cleanup_suppressed


def test_unresolved_page_reference_is_not_downgraded_to_media_warning(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {"wiki/page.md": document(WIKI_ID, "Page", "See [missing](wiki:not-there).")},
    )
    source = make_source()
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter), pytest.raises(Exception, match="finished with 1 error"):
        run_parser(WikiParser(), repository, source)

    missing.refresh_from_db()
    assert missing.status != STATUS_DRAFT
    assert not KnowledgeBasePage.objects.filter(slug="page").exists()
    assert adapter.reports[0].cleanup_suppressed
    assert adapter.reports[0].errors[0].step != "image_reference_missing"


def test_fatal_boundary_reports_once_and_skips_sibling_cleanup_and_completion(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/01-first.md": document(WIKI_ID, "First"),
            "wiki/02-boundary.md": document(SECOND_WIKI_ID, "Boundary"),
            "wiki/03-later.md": document("66666666-6666-4666-8666-666666666666", "Later"),
        },
    )
    source = make_source()
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()
    adapter.boundary_path = "wiki/02-boundary.md"

    with page_site_adapter(adapter), package_page_parsers():
        log = sync_content_source(source, repo_dir=repository)

    missing.refresh_from_db()
    assert KnowledgeBasePage.objects.filter(slug="first").exists()
    assert not KnowledgeBasePage.objects.filter(slug="later").exists()
    assert missing.status != STATUS_DRAFT
    assert_boundary_result(adapter, log)


def test_manifest_diagnostic_is_global_to_both_declared_page_families(tmp_path):
    manifest = collections_manifest("wiki", "docs", extra="unexpected: true")
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/page.md": document(WIKI_ID, "Page"),
            "docs/index.md": document(SECOND_WIKI_ID, "Docs"),
        },
        manifest=manifest,
    )
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter):
        for parser in (WikiParser(), DocsParser()):
            with pytest.raises(KnowledgeBaseParseError, match="finished with 1 error"):
                run_parser(parser, repository, make_source())

    assert {report.section for report in adapter.reports} == {SECTION_WIKI, SECTION_DOCS}
    assert all(report.cleanup_suppressed for report in adapter.reports)
    assert all(report.errors[0].source_path == "content.yaml" for report in adapter.reports)


def test_root_collection_diagnostic_is_attributed_without_prefix_guessing(tmp_path):
    manifest = "schema_version: 1\ncollections:\n  - kind: wiki\n    path: .\n"
    repository = write_repository(
        tmp_path / "repo",
        {
            "01-bad.md": "---\ntitle: Missing identity\n---\n\nBad.\n",
            "02-good.md": document(WIKI_ID, "Good"),
        },
        manifest=manifest,
    )
    adapter = RecordingPageAdapter()

    with (
        page_site_adapter(adapter),
        pytest.raises(KnowledgeBaseParseError, match="finished with 2 error"),
    ):
        run_parser(WikiParser(), repository, make_source())

    assert KnowledgeBasePage.objects.filter(slug="good").exists()
    paths = {error.source_path for error in adapter.reports[0].errors}
    assert paths == {"01-bad.md", "content.yaml"}
    assert adapter.reports[0].cleanup_suppressed


def test_course_person_and_article_diagnostics_do_not_change_wiki_cleanup(tmp_path):
    manifest = collections_manifest("wiki", "course", "person", "article")
    repository = write_repository(
        tmp_path / "repo",
        {
            "wiki/good.md": document(WIKI_ID, "Good"),
            "course/bad.md": "---\ntitle: Missing course\n---\n\nBad.\n",
            "people/bad.md": "---\ntitle: Missing identity\n---\n\nBad.\n",
            "article/bad.md": "---\ntitle: Missing directory\n---\n\nBad.\n",
        },
        manifest=manifest,
    )
    source = make_source()
    missing = old_page(source, "missing", "wiki/missing.md")
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter):
        run_parser(WikiParser(), repository, source)

    missing.refresh_from_db()
    assert missing.status == STATUS_DRAFT
    assert adapter.reports[0].errors == ()


def test_unconfigured_default_mode_keeps_strict_missing_asset_refusal(tmp_path):
    repository = write_repository(
        tmp_path / "repo",
        {"wiki/page.md": document(WIKI_ID, "Page", "![Missing](images/no.png)")},
    )

    with pytest.raises(KnowledgeBaseParseError, match="unresolved references or assets"):
        run_parser(WikiParser(), repository, make_source())

    assert not KnowledgeBasePage.objects.exists()
