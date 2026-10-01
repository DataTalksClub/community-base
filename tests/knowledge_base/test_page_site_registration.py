"""Registration and observer failure contracts for page site adapters."""

from unittest.mock import patch

import pytest

from community_base.knowledge_base.content_sync_parsers import KnowledgeBaseParseError, WikiParser
from community_base.knowledge_base.page_adaptation import (
    PageBoundaryFailure,
    PageError,
    page_site_adapter,
    register_page_site_adapter,
)
from tests.knowledge_base.page_site_fixtures import (
    WIKI_ID,
    RecordingPageAdapter,
    document,
    write_repository,
)
from tests.knowledge_base.test_page_site_adapter import run_parser
from tests.knowledge_base.utils import make_source

pytestmark = pytest.mark.django_db


def test_adapter_lookup_happens_at_discovery_and_registration_does_not_leak(tmp_path):
    repository = write_repository(tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page")})
    early_parser = WikiParser()
    first = RecordingPageAdapter()

    with page_site_adapter(first):
        run_parser(early_parser, repository, make_source())
        with pytest.raises(ValueError, match="already registered"):
            register_page_site_adapter(RecordingPageAdapter())

    with page_site_adapter(RecordingPageAdapter()):
        run_parser(WikiParser(), repository, make_source())

    assert len(first.reports) == 1


def test_final_report_failure_is_visible(tmp_path):
    repository = write_repository(tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page")})
    adapter = RecordingPageAdapter()
    adapter.raise_finished = True

    with page_site_adapter(adapter), pytest.raises(RuntimeError, match="final reporter failed"):
        run_parser(WikiParser(), repository, make_source())


def test_error_reporter_failure_is_visible_with_original_context(tmp_path):
    class BrokenReporter(RecordingPageAdapter):
        def describe_error(self, context, source_path, error, traceback):
            raise RuntimeError("error reporter failed") from error

    repository = write_repository(tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page")})
    adapter = BrokenReporter()
    adapter.fail_path = "wiki/page.md"

    with page_site_adapter(adapter), pytest.raises(RuntimeError, match="error reporter failed"):
        run_parser(WikiParser(), repository, make_source())


def test_undeclared_page_kind_never_projects_or_reports(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    adapter = RecordingPageAdapter()

    with page_site_adapter(adapter):
        items, results, deleted = run_parser(WikiParser(), repository, make_source())

    assert (items, results, deleted) == ([], [], [])
    assert adapter.reports == []


def test_cleanup_storage_failure_is_reported_with_live_traceback(tmp_path):
    repository = write_repository(tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page")})
    adapter = RecordingPageAdapter()

    with (
        page_site_adapter(adapter),
        patch("community_base.knowledge_base.sync.delete_missing", side_effect=RuntimeError("db")),
        pytest.raises(KnowledgeBaseParseError, match="cleanup failed"),
    ):
        run_parser(WikiParser(), repository, make_source())

    report = adapter.reports[0]
    assert not report.completed
    assert report.cleanup_suppressed
    assert report.errors[0].source_path == "<cleanup>"
    assert adapter.tracebacks[0] is not None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"step": "page_storage"}, "require step=filesystem_boundary"),
        ({"kind": ""}, "kind must be a nonempty string"),
        ({"filesystem_boundary": False}, "requires a boundary error"),
        ({"filesystem_boundary": 1}, "must be true or false"),
        ({"retryable": True}, "cannot be retryable"),
        ({"retryable": 0}, "must be true or false"),
    ],
)
def test_boundary_error_rejects_contradictory_invariants(overrides, message):
    values = {
        "file": "wiki/page.md",
        "error": "checkout changed",
        "step": "filesystem_boundary",
        "kind": "outside_checkout",
        "filesystem_boundary": True,
        "retryable": False,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        PageError(**values)


def test_boundary_failure_rejects_untyped_and_ordinary_errors():
    ordinary = PageError("wiki/page.md", "failed", "page_storage", "storage")
    with pytest.raises(TypeError, match="typed filesystem boundary"):
        PageBoundaryFailure(ordinary)
    with pytest.raises(TypeError):
        PageError(file="wiki/page.md", error="failed", step="filesystem_boundary")


def test_error_reporter_cannot_replace_the_active_path(tmp_path):
    class WrongPathReporter(RecordingPageAdapter):
        def describe_error(self, context, source_path, error, traceback):
            return PageError("wiki/other.md", "failed", "page_projection", "projection")

    repository = write_repository(tmp_path / "repo", {"wiki/page.md": document(WIKI_ID, "Page")})
    adapter = WrongPathReporter()
    adapter.fail_path = "wiki/page.md"

    with page_site_adapter(adapter), pytest.raises(ValueError, match="active source path"):
        run_parser(WikiParser(), repository, make_source())
