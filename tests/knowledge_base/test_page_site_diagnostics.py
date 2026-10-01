"""Collection attribution and diagnostic redaction for adapted pages."""

import pytest

from community_base.knowledge_base.content_sync_parsers import KnowledgeBaseParseError, WikiParser
from community_base.knowledge_base.models import SECTION_WIKI, STATUS_DRAFT, KnowledgeBasePage
from community_base.knowledge_base.page_adaptation import page_site_adapter
from community_base.knowledge_base.sync import upsert_page
from tests.knowledge_base.page_site_fixtures import (
    WIKI_ID,
    RecordingPageAdapter,
    collections_manifest,
    document,
    write_repository,
)
from tests.knowledge_base.test_page_site_adapter import run_parser
from tests.knowledge_base.utils import COMMIT_SHA, make_source

pytestmark = pytest.mark.django_db
ERROR_FIELDS = {
    "file",
    "error",
    "step",
    "kind",
    "filesystem_boundary",
    "retryable",
}


def old_wiki_page(source):
    return upsert_page(
        source,
        section=SECTION_WIKI,
        slug="missing",
        title="Missing",
        commit_sha=COMMIT_SHA,
        source_path="wiki/missing.md",
        checksum="1" * 64,
    )[0]


def test_ambiguous_overlapping_root_fails_closed_and_reports_its_path(tmp_path):
    manifest = (
        collections_manifest(
            "wiki",
            "course",
        )
        .replace("path: wiki", "path: content")
        .replace("path: course", "path: content/course")
    )
    repository = write_repository(
        tmp_path / "repo",
        {
            "content/good.md": document(WIKI_ID, "Good"),
            "content/course/bad.md": "---\ntitle: Bad\n---\n\nBad.\n",
        },
        manifest=manifest,
    )
    source = make_source()
    missing = old_wiki_page(source)
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter), pytest.raises(KnowledgeBaseParseError):
        run_parser(WikiParser(), repository, source)

    missing.refresh_from_db()
    report = adapter.reports[0]
    assert missing.status != STATUS_DRAFT
    assert KnowledgeBasePage.objects.filter(slug="good").exists()
    assert report.cleanup_suppressed
    assert "content/course" in {error.source_path for error in report.errors}


def test_manifest_and_path_diagnostics_redact_source_canary(tmp_path):
    canary = "secret-not-used-here"
    manifest = collections_manifest("wiki", extra=f"{canary}: true")
    repository = write_repository(
        tmp_path / "repo",
        {
            f"wiki/{canary}.md": "---\ntitle: Missing identity\n---\n\nBad.\n",
            "wiki/good.md": document(WIKI_ID, "Good"),
        },
        manifest=manifest,
    )
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter), pytest.raises(KnowledgeBaseParseError):
        run_parser(WikiParser(), repository, make_source())

    report = adapter.reports[0]
    assert canary not in repr(report)
    assert report.cleanup_suppressed
    assert all(set(error.record) == ERROR_FIELDS for error in report.errors)
