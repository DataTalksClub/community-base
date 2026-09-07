"""Shared fixture helpers: wrap fixture directories in an ImmutableCheckout."""

import hashlib
from pathlib import Path

from django.test import TestCase

from community_base.content_sync.checkout import ImmutableCheckout
from community_base.content_sync.models import ContentSource

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AISL_CONTENT = FIXTURES / "aisl-content"
DTC_REPO = FIXTURES / "dtc-repo"


def make_source(slug="fixture-source", repo="example/fixture"):
    source, _created = ContentSource.objects.get_or_create(
        slug=slug,
        defaults={"repo_name": repo, "webhook_secret": "secret-not-used-here"},
    )
    return source


def checkout(path: Path, commit_sha: str = ""):
    return ImmutableCheckout(path, commit_sha=commit_sha)


class ParserHarness(TestCase):
    """Runs one parser against a fixture directory, like the sync would."""

    def run_parser(self, parser, fixture: Path, commit_sha: str = ""):
        source, items, results, deleted = self.run_parser_with_source(
            parser, fixture, commit_sha=commit_sha
        )
        return source, items, results, deleted

    def run_parser_with_source(
        self,
        parser,
        fixture: Path,
        *,
        slug="fixture-source",
        repo=None,
        commit_sha: str = "",
    ):
        source = make_source(slug=slug, repo=repo or f"example/{slug}")
        with checkout(fixture, commit_sha=commit_sha) as active:
            items = list(parser.discover(active, source))
            results = [parser.upsert(item, source, None) for item in items]
            deleted = parser.soft_delete_missing({item.key for item in items}, source)
        return source, items, results, list(deleted)


def sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
