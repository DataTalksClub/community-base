"""The knowledge base search corpus, provided as a service.

Sites call these functions from their own search views; the package ships no
view, feed, sitemap or robots output. DTC's feed, sitemap and robots output
stay site-owned because they are site-shaped. The corpus is built from the
stored, sanitized ``body_html`` -- rendering happened once at save time, so
search never re-renders markdown.

``corpus_stamp()`` moves exactly when a sync could have changed pages (count
plus latest ``updated_at``), so a site that caches the corpus can key its cache
on the stamp the way the DTC docs projection does. A zero count is an empty
corpus, not a failure.
"""

import html
import re
from dataclasses import dataclass
from functools import lru_cache

from django.db.models import Count, Max, QuerySet

from community_base.knowledge_base.models import STATUS_PUBLISHED, KnowledgeBasePage

DEFAULT_LIMIT = 100

_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class CorpusEntry:
    """One searchable page: the identity a site needs to link the result."""

    section: str
    slug: str
    title: str
    summary: str
    haystack: str


def corpus_stamp() -> tuple[int, str]:
    """A cheap stamp that moves whenever the published pages could have."""

    stamp = KnowledgeBasePage.objects.filter(status=STATUS_PUBLISHED).aggregate(
        total=Count("id"), latest=Max("updated_at")
    )
    return (int(stamp["total"] or 0), str(stamp["latest"] or ""))


def _body_text(body_html: str) -> str:
    return html.unescape(" ".join(_TAGS.sub(" ", body_html).split()))


def _entries(pages: QuerySet) -> tuple[CorpusEntry, ...]:
    return tuple(
        CorpusEntry(
            section=page.section,
            slug=page.slug,
            title=page.title,
            summary=page.summary,
            haystack=" ".join((page.title, page.summary, _body_text(page.body_html))).casefold(),
        )
        for page in pages
    )


@lru_cache(maxsize=8)
def _cached_corpus(stamp: tuple[int, str], section: str | None) -> tuple[CorpusEntry, ...]:
    if not stamp[0]:
        return ()
    pages = KnowledgeBasePage.objects.filter(status=STATUS_PUBLISHED).order_by("section", "slug")
    if section is not None:
        pages = pages.filter(section=section)
    return _entries(pages)


def search_corpus(section: str | None = None) -> tuple[CorpusEntry, ...]:
    """The full corpus, optionally limited to one section."""

    return _cached_corpus(corpus_stamp(), section)


def search_pages(
    query: str, section: str | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[CorpusEntry, ...]:
    """Pages whose title, summary, or body match every term.

    Terms are ANDed and matched case-insensitively; results are capped so a
    broad term cannot return the whole corpus at once. The cap cannot be
    raised above ``DEFAULT_LIMIT`` by passing a larger ``limit``.
    """

    terms = query.casefold().split()
    if not terms:
        return ()
    results: list[CorpusEntry] = []
    cap = max(0, min(limit, DEFAULT_LIMIT))
    for entry in search_corpus(section):
        if all(term in entry.haystack for term in terms):
            results.append(entry)
            if len(results) >= cap:
                break
    return tuple(results)
