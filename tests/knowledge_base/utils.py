"""Shared helpers for the knowledge base tests."""

from pathlib import Path

from django.test import TestCase

from community_base.content_sync.checkout import ImmutableCheckout
from community_base.content_sync.models import ContentSource

FIXTURES = Path(__file__).resolve().parent / "fixtures"
KB_REPO = FIXTURES / "kb-repo"
DOCS_TREE_REPO = FIXTURES / "docs-tree-repo"

# upsert_page validates the full 40-hex commit the sync orchestration would pass.
COMMIT_SHA = "b" * 40


def make_source(slug="kb-fixture", repo="example/kb-fixture"):
    source, _created = ContentSource.objects.get_or_create(
        slug=slug,
        defaults={"repo_name": repo, "webhook_secret": "secret-not-used-here"},
    )
    return source


def checkout(path: Path, commit_sha: str = COMMIT_SHA):
    return ImmutableCheckout(path, commit_sha=commit_sha)


class ParserHarness(TestCase):
    """Runs one parser against a fixture directory, like the sync would."""

    def run_parser(self, parser, fixture: Path, *, commit_sha: str = COMMIT_SHA):
        source = make_source()
        with checkout(fixture, commit_sha=commit_sha) as active:
            items = list(parser.discover(active, source))
            results = [parser.upsert(item, source, None) for item in items]
            deleted = parser.soft_delete_missing({item.key for item in items}, source)
        return source, items, results, list(deleted)
