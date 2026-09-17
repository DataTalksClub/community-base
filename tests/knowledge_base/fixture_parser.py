"""A fixture ``content_sync`` parser for the knowledge base tests.

Layout under the fixture root:

- ``wiki/<slug>.md`` -- flat wiki pages;
- ``docs/<slug>.md`` -- documentation pages; front matter ``parent:`` names the
  parent slug, ``nav_order:`` positions the page among its siblings.

Item keys are ``<section>:<slug>`` so one run can carry the same slug in both
sections without colliding. Docs items are emitted parents-first (a page only
after its parent), which the upsert contract requires.
"""

import hashlib
import json
from pathlib import PurePosixPath

import yaml

from community_base.content_sync.orchestration import UpsertResult
from community_base.content_sync.parsers import SourceItem
from community_base.knowledge_base import sync
from community_base.knowledge_base.models import SECTION_DOCS, SECTION_WIKI

WIKI_ROOT = "wiki"
DOCS_ROOT = "docs"


def parse_fixture_page(text: str) -> tuple[dict, str]:
    """Split a fixture file into (front matter mapping, body)."""

    if text.startswith("---"):
        end = text.find("\n---", 3)
        metadata = yaml.safe_load(text[3:end]) or {}
        body = text[end + 4 :].lstrip("\n")
        return metadata, body
    return {}, text


class KbFixtureParser:
    """The parser a site would write against the app's upsert contract."""

    def __init__(self):
        self._checkout = None

    def discover(self, checkout, source):
        self._checkout = checkout
        pages: dict[tuple[str, str], tuple[PurePosixPath, dict, str]] = {}
        for path in self._markdown_paths(checkout):
            metadata, body = parse_fixture_page(checkout.read_text(path.as_posix()))
            pages[(path.parts[0], self._slug_of(path))] = (path, metadata, body)

        items: list[SourceItem] = []
        for section in (SECTION_WIKI, SECTION_DOCS):
            emitted: set[str] = set()
            pending = sorted(slug for sec, slug in pages if sec == section)
            while pending:
                remaining: list[str] = []
                progressed = False
                for slug in pending:
                    parent_slug = pages[(section, slug)][1].get("parent") or None
                    if parent_slug is None or parent_slug in emitted:
                        items.append(self._item(*pages[(section, slug)]))
                        emitted.add(slug)
                        progressed = True
                    else:
                        remaining.append(slug)
                if not progressed:
                    raise ValueError(f"Fixture {section} pages have an unknown or cyclic parent")
                pending = remaining
        return items

    def upsert(self, item, source, media):
        data = item.data
        page, action = sync.upsert_page(
            source,
            section=data["section"],
            slug=data["slug"],
            title=data["title"],
            body=data["body"],
            summary=data["summary"],
            parent_slug=data["parent_slug"],
            nav_order=data["nav_order"],
            commit_sha=item.data["commit_sha"],
            source_path=data["source_path"],
            checksum=data["checksum"],
        )
        return UpsertResult(page, action)

    def soft_delete_missing(self, seen_keys, source):
        drafted: list = []
        for section in (SECTION_WIKI, SECTION_DOCS):
            prefix = f"{section}:"
            slugs = {key[len(prefix) :] for key in seen_keys if key.startswith(prefix)}
            drafted.extend(sync.delete_missing(source, section, slugs))
        return drafted

    def _markdown_paths(self, checkout):
        paths = []
        for relative in checkout.files():
            path = PurePosixPath(str(relative))
            if path.suffix == ".md" and path.parts[0] in (WIKI_ROOT, DOCS_ROOT):
                paths.append(path)
        return sorted(paths, key=lambda path: path.as_posix())

    @staticmethod
    def _slug_of(path: PurePosixPath) -> str:
        return "/".join(path.with_suffix("").parts[1:])

    @staticmethod
    def _render(slug: str, title: str, body: str) -> str:
        """The site's own rendering: a wrapper and an anchored heading."""

        paragraphs = "".join(f"<p>{line}</p>" for line in body.strip().splitlines() if line.strip())
        return f'<div class="site-rendered"><h2 id="{slug}-heading">{title}</h2>{paragraphs}</div>'

    def _item(self, path: PurePosixPath, metadata: dict, body: str) -> SourceItem:
        source_path = path.as_posix()
        section = path.parts[0]
        slug = self._slug_of(path)
        parent_slug = metadata.get("parent") or None
        nav_order = int(metadata.get("nav_order") or 0)
        checksum = hashlib.sha256(
            "|".join(
                (source_path, parent_slug or "", body, json.dumps(metadata, sort_keys=True))
            ).encode()
        ).hexdigest()
        return SourceItem(
            key=f"{section}:{slug}",
            path=path,
            data={
                "section": section,
                "slug": slug,
                "title": str(metadata.get("title") or slug),
                "summary": str(metadata.get("summary") or ""),
                "body": body,
                "parent_slug": parent_slug,
                "nav_order": nav_order,
                "source_path": source_path,
                "checksum": checksum,
                "commit_sha": self._checkout.commit_sha,
            },
        )


class KbDocsTreeFixtureParser:
    """A documentation-tree parser shaped like DataTalks.Club's docs parser.

    Layout under the fixture root: ``docs/<dir>/.../<stem>.md``. A directory's
    own page is its ``index.md``; every other file is a leaf page of that
    directory. The page slug is the leaf segment only, so the same slug
    (``project``) repeats under different parents, and the path is carried by
    ``parent_path``. Item keys are source paths, which identify a page even
    when its slug does not. The public path comes from the source file, not
    from the parent links, the way the DataTalks.Club docs parser derives it,
    and the parser renders the body itself: the heading carries the anchor id
    the site's table of contents links to, which the app's markdown renderer
    does not emit.
    """

    def __init__(self):
        self._checkout = None

    def discover(self, checkout, source):
        self._checkout = checkout
        items: list[SourceItem] = []
        paths = [
            PurePosixPath(str(relative))
            for relative in checkout.files()
            if PurePosixPath(str(relative)).suffix == ".md"
            and PurePosixPath(str(relative)).parts[0] == DOCS_ROOT
        ]
        # Parents before children: a shorter chain is always an ancestor's, and
        # a directory's own index.md precedes the leaves beside it.
        for path in sorted(paths, key=lambda path: (len(self._chain(path)), path.as_posix())):
            metadata, body = parse_fixture_page(checkout.read_text(path.as_posix()))
            items.append(self._item(path, metadata, body))
        return items

    def upsert(self, item, source, media):
        data = item.data
        page, action = sync.upsert_page(
            source,
            section=SECTION_DOCS,
            slug=data["slug"],
            title=data["title"],
            body=data["body"],
            parent_path=data["parent_path"],
            nav_order=data["nav_order"],
            public_path=data["public_path"],
            body_html=data["body_html"],
            commit_sha=data["commit_sha"],
            source_path=data["source_path"],
            checksum=data["checksum"],
        )
        return UpsertResult(page, action)

    def soft_delete_missing(self, seen_keys, source):
        return sync.delete_missing(source, SECTION_DOCS, seen_source_paths=set(seen_keys))

    @staticmethod
    def _chain(path: PurePosixPath) -> list[str]:
        """The slug chain from the section root down to this page."""

        parts = list(path.with_suffix("").parts[1:])
        if parts[-1] == "index":
            parts.pop()
        return parts

    @staticmethod
    def _render(slug: str, title: str, body: str) -> str:
        """The site's own rendering: a wrapper and an anchored heading."""

        paragraphs = "".join(f"<p>{line}</p>" for line in body.strip().splitlines() if line.strip())
        return f'<div class="site-rendered"><h2 id="{slug}-heading">{title}</h2>{paragraphs}</div>'

    def _item(self, path: PurePosixPath, metadata: dict, body: str) -> SourceItem:
        source_path = path.as_posix()
        chain = self._chain(path)
        slug = chain[-1] if chain else "index"
        parent_path = "/".join(chain[:-1]) or None
        nav_order = int(metadata.get("nav_order") or 0)
        title = str(metadata.get("title") or slug)
        checksum = hashlib.sha256(
            "|".join(
                (source_path, parent_path or "", body, json.dumps(metadata, sort_keys=True))
            ).encode()
        ).hexdigest()
        return SourceItem(
            key=source_path,
            path=path,
            data={
                "slug": slug,
                "title": title,
                "body": body,
                "parent_path": parent_path,
                "nav_order": nav_order,
                "public_path": "/docs/" + "".join(f"{segment}/" for segment in chain),
                "body_html": self._render(slug, title, body),
                "source_path": source_path,
                "checksum": checksum,
                "commit_sha": self._checkout.commit_sha,
            },
        )
