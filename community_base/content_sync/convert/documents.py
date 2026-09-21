"""Convert one document collection to the content format (`FORMAT.md` 3.2-3.7).

    uv run python -m community_base.content_sync.convert.documents <path> --profile <name>

Deleted from this package after the last conversion merges, which is `D7.4`
step 9, as `courses.py` is.

A document collection is a Jekyll-shaped repository: an underscore directory of
markdown files with front matter written for a Jekyll layout, Liquid in the
bodies and kramdown attribute lists under the headings. There are eight of
them and no two are shaped alike, so the rules are declared per repository in
`PROFILES` and the engine below is the same for all of them:

- files move from the source directory to the target one, renamed to the shape
  the kind's layout wants (`<slug>.md` for a flat collection,
  `<slug>/index.md` for an item directory, `<id>.md` for a person);
- keys are renamed, dropped or moved under `extra`, one rule per key, and the
  report prints the value of every key that is dropped;
- `content_id` is minted where the file carries none, as a version 5 UUID of
  the repository namespace and the target path, so a second run mints the same
  one and a re-run during the freeze window does not re-identify the page;
- bodies lose kramdown attribute lists, Liquid `relative_url` links become
  relative file links, and `[[wikilinks]]` become typed references through the
  title map the collection itself provides;
- `content.yaml` is written last, from the collections the profile declares.

What it refuses, rather than guess:

- a file whose name does not reduce to a slug, which is the `_template` and
  `ella(wati)sahnan` case of the DataTalks.Club people directory;
- a `[[wikilink]]` or a `related:` title that names no page of the collection,
  which the DataTalks.Club podwiki parser drops silently today;
- a Liquid construct that is not a `relative_url` link, because rewriting one
  means knowing what it rendered to;
- front matter that does not parse, and a target path two files would land on.

A refusal leaves its file where it was and names it in the report. The three
human-review concentrations of the specification's section 5 come out of that
report: the rendering diff of the DataTalks.Club articles, the re-parented
documentation pages of decision D28, and the podwiki tokens that resolve to
nothing.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from community_base.content_sync.convert.report import (
    ConversionReport,
    dump_yaml,
    inventory,
    ordered,
    read_front_matter,
    write_front_matter,
)

__all__ = ["PROFILES", "Collection", "Profile", "convert_documents", "main"]

MANIFEST_NAME = "content.yaml"

CORE_ORDER = (
    "content_id",
    "title",
    "slug",
    "summary",
    "status",
    "required_level",
    "sort_order",
    "tags",
    "image",
    "date",
)

#: `FORMAT.md` section 3.4: a name that is a date is a date, not an order.
DATE_NAME = re.compile(r"^(?:(?P<century>\d{2})?(?P<year>\d{2})-(?P<month>\d{2})-(?P<day>\d{2}))-")
SLUG_OK = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ORDER_PREFIX = re.compile(r"^\d{2,3}-(?=.)")

KRAMDOWN_LINE = re.compile(r"^\s*\{:\s*[.#][^}]*\}\s*$")
KRAMDOWN_INLINE = re.compile(r"\s*\{:\s*[.#][^}]*\}")
RELATIVE_URL = re.compile(r"\{\{\s*'(?P<path>[^']+)'\s*\|\s*relative_url\s*\}\}")
SITE_BASEURL = re.compile(r"\{\{\s*site\.baseurl\s*\}\}(?P<path>\S*)")
LIQUID = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
STYLE_ATTRIBUTE = re.compile(r'\s+style\s*=\s*(["\'])[^"\']*\1', re.IGNORECASE)
STRIKETHROUGH = re.compile(r"~~([^~\s][^~]*)~~")
FENCE = re.compile(r"^(\s*)(```+|~~~+)")
INLINE_CODE = re.compile(r"`[^`]*`")
ABSOLUTE_LINK = re.compile(r"(?P<open>!?\[[^\]]*\]\()(?P<path>/[^)\s]*)\)")
ABSOLUTE_SRC = re.compile(r"(?P<open>\bsrc\s*=\s*[\"'])(?P<path>/[^\"']*)")


class Refused(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


# --- what a repository declares -----------------------------------------------


@dataclass(frozen=True)
class Collection:
    """One collection of one repository, and the rules it converts under."""

    kind: str
    source: str
    target: str
    #: `flat` is `<slug>.md`, `item` is `<slug>/index.md`, `tree` keeps the
    #: directory chain, `data` copies the file and reads nothing inside it.
    layout: str = "flat"
    rename: Mapping[str, str] = field(default_factory=dict)
    drop: tuple[str, ...] = ()
    keep: tuple[str, ...] = ()
    #: Keys whose value is a list of titles of this collection's own pages.
    title_references: tuple[str, ...] = ()
    #: Keys whose value is a list of slugs of this collection's own pages.
    slug_references: tuple[str, ...] = ()
    #: `{label: front matter key}` collapsed into the person kind's `links`.
    link_keys: Mapping[str, str] = field(default_factory=dict)
    #: YAML file name a `yaml` collection rewrites in place (`workshop.yaml`).
    manifest: str = ""
    #: Take `date` out of a `YY-MM-DD-` or `YYYY-MM-DD-` name prefix.
    date_from_name: bool = False
    #: Directories of assets that move with the collection.
    assets: Mapping[str, str] = field(default_factory=dict)
    #: Build the tree from `parent:` and `grand_parent:` titles (decision D28).
    parent_titles: bool = False
    #: Rewrite a Jekyll site path (`/courses/x/`) to a relative file link.
    jekyll_urls: bool = False
    #: The path Jekyll served this collection under (`/course-wiki`).
    url_prefix: str = ""
    #: Repository directories an absolute `/dir/...` reference names.
    absolute_roots: tuple[str, ...] = ()
    #: The files and directories of `source` this collection walks; all of them
    #: when empty. A repository whose collection root is the repository root
    #: needs it, because the repository also holds its own tooling.
    roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    """One repository: its collections, its ignores and what it is called."""

    name: str
    collections: tuple[Collection, ...]
    ignore: tuple[str, ...] = ()
    strict_references: bool | None = None
    theme_pairs: bool = False


PROFILES: dict[str, Profile] = {}


def _register(profile: Profile) -> Profile:
    PROFILES[profile.name] = profile
    return profile


_register(
    Profile(
        name="aisl-wiki",
        collections=(
            Collection(
                kind="wiki",
                source="_wiki",
                target="wiki",
                layout="flat",
                drop=("layout",),
                slug_references=("related",),
            ),
        ),
    )
)

_register(
    Profile(
        name="podwiki",
        collections=(
            Collection(
                kind="wiki",
                source="_course_wiki",
                target="wiki",
                layout="flat",
                drop=("layout",),
                rename={"related_course": "related"},
                title_references=("related",),
                jekyll_urls=True,
                url_prefix="/course-wiki",
            ),
            Collection(kind="data", source="graph", target="data/graph", layout="data"),
            Collection(kind="data", source="search", target="data/search", layout="data"),
        ),
    )
)

_register(
    Profile(
        name="dtc-people",
        collections=(
            Collection(
                kind="person",
                source="_people",
                target="people",
                layout="flat",
                rename={"picture": "image", "bio_short": "summary"},
                drop=("layout", "short"),
                link_keys={
                    "linkedin": "linkedin",
                    "github": "github",
                    "x": "twitter",
                    "website": "web",
                    "youtube": "youtube",
                },
                assets={"images/authors": "people/images"},
            ),
        ),
    )
)

_register(
    Profile(
        name="dtc-articles",
        collections=(
            Collection(
                kind="article",
                source="articles",
                target="articles",
                layout="item",
                rename={"description": "summary"},
                drop=("layout", "datepublished"),
                date_from_name=True,
                absolute_roots=("images",),
            ),
        ),
        ignore=("books/**", "podcasts/**", "scripts/**", "migration/**", "tests/**"),
    )
)

_register(
    Profile(
        name="dtc-docs",
        collections=(
            Collection(
                kind="docs",
                source=".",
                target="docs",
                layout="tree",
                rename={"nav_order": "sort_order", "description": "summary"},
                drop=("layout", "parent", "grand_parent", "has_children", "has_toc", "permalink"),
                #: The tree comes from `parent:` and `grand_parent:` titles, not
                #: from the directories: decision D28 takes the nested paths the
                #: section parents imply.
                parent_titles=True,
                jekyll_urls=True,
                absolute_roots=("assets",),
                roots=("index.md", "activities", "courses", "general"),
            ),
        ),
        ignore=("drafts/**", "scripts/**", "tests/**", "touch/**"),
    )
)

_register(
    Profile(
        name="faq",
        collections=(
            # Decision D26: the FAQ keeps its current file shape. The only
            # change is the directory name and `content.yaml`, so the files
            # move verbatim and nothing inside one is read.
            Collection(kind="faq", source="_questions", target="faq", layout="opaque"),
        ),
        ignore=("faq_automation/**", "scripts/**", "website/**", "docs/**"),
    )
)

_register(
    Profile(
        name="aisl-content",
        collections=(
            Collection(
                kind="article",
                source="blog",
                target="articles",
                layout="item",
                rename={
                    "description": "summary",
                    "cover_image": "image",
                    "author": "byline",
                },
                keep=("faq",),
            ),
            Collection(
                kind="project",
                source="projects",
                target="projects",
                layout="item",
                rename={
                    "description": "summary",
                    "cover_image": "image",
                    "author": "byline",
                },
                keep=("difficulty",),
            ),
            Collection(
                kind="curated_link",
                source="curated-links",
                target="curated-links",
                layout="flat",
                keep=("url", "category", "published"),
            ),
            Collection(
                kind="interview_question",
                source="interview-questions",
                target="interview-questions",
                layout="flat",
                rename={"description": "summary"},
                keep=("sections", "status"),
            ),
            Collection(kind="data", source="tiers.yaml", target="data", layout="data"),
            Collection(kind="course", source="courses", target="courses", layout="declare"),
        ),
        ignore=("events/**", "scripts/**", "widgets/**", "resources/**"),
    )
)

_register(
    Profile(
        name="aisl-workshops",
        collections=(
            Collection(
                kind="workshop",
                source=".",
                target=".",
                layout="yaml",
                manifest="workshop.yaml",
                rename={
                    "cover_image_url": "image",
                    "instructor_name": "byline",
                },
                keep=(
                    "slug",
                    "event_slug",
                    "pages_required_level",
                    "landing_required_level",
                    "code_repo_url",
                    "materials",
                    "recording",
                    "tags",
                ),
            ),
        ),
        ignore=(
            "scripts/**",
            "_docs/**",
            ".venv/**",
        ),
    )
)


# --- the entry point ----------------------------------------------------------


def convert_documents(root: Path, profile: Profile, *, apply: bool = True) -> ConversionReport:
    """Convert the document collections of `root` in place and report on it."""

    root = Path(root)
    report = ConversionReport(repository=profile.name, before=inventory(root))
    _Conversion(root, profile, report, apply=apply).run()
    report.after = inventory(root)
    return report


class _Conversion:
    """One pass over one repository; nothing is written before the walk ends."""

    def __init__(
        self, root: Path, profile: Profile, report: ConversionReport, *, apply: bool
    ) -> None:
        self.root = root
        self.profile = profile
        self.report = report
        self.apply = apply
        self.namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"datatalksclub:{profile.name}")
        self.writes: list[tuple[str, str]] = []
        self.copies: list[tuple[str, str]] = []
        self.removals: list[str] = []
        self.touched: set[str] = set()
        self.known_slugs: set[str] = set()
        self.urls: dict[str, str] = {}

    # -- the walk ------------------------------------------------------------

    def run(self) -> None:
        for collection in self.profile.collections:
            self._convert_collection(collection)
        self._write_manifest()
        self._account()
        self._flush()

    def _convert_collection(self, collection: Collection) -> None:
        if collection.layout == "declare":
            return
        path = self.root / collection.source
        if collection.layout == "yaml":
            self._convert_yaml_collection(collection)
            return
        if collection.layout in ("data", "opaque"):
            target = f"{collection.target.rstrip('/')}/{path.name}"
            if path.is_file():
                self.copies.append((collection.source, target))
                self.report.record(
                    collection.source,
                    "renamed",
                    target=target,
                    details=["carried across unread"],
                )
                self.touched.add(collection.source)
                return
            if (self.root / target).is_file():
                # A previous run already moved the file; a second run is a no-op.
                return
        directory = path
        if not directory.is_dir():
            already = self.root / collection.target
            if already.exists() and collection.source != collection.target:
                # A previous run moved the collection; a second run is a no-op.
                return
            self.report.refuse(
                collection.source, "3.1", "the profile names a directory that is not there"
            )
            return
        if collection.layout in ("data", "opaque"):
            self._move_verbatim(collection, directory)
            return
        pages = self._pages(collection, directory)
        titles = {
            str(page["front"].get("title") or "").strip().lower(): page["slug"] for page in pages
        }
        slugs = {page["slug"] for page in pages}
        self.known_slugs = slugs
        self._place(collection, pages)
        self.urls = _jekyll_urls(collection, pages) if collection.jekyll_urls else {}
        landing: dict[str, str] = {}
        for page in pages:
            try:
                self._convert_page(collection, page, titles, slugs, landing)
            except Refused as refusal:
                self.report.refuse(page["source"], refusal.rule, refusal.message)
                self.report.record(page["source"], "refused")
                self.touched.add(page["source"])
        for source, target in collection.assets.items():
            self._move_assets(source, target)

    def _place(self, collection: Collection, pages: list[dict[str, Any]]) -> None:
        """Give every page its target path, and the tree its shape.

        Without `parent_titles` the directory chain is the tree, which is what
        the format says. With it, a page whose `parent:` names a sibling page
        moves under that page, which becomes a node with `index.md`: that is
        decision D28 and the twenty-five DataTalks.Club documentation pages it
        is about. The pass repeats until nothing moves, so a chain of parents
        resolves in the order the tree implies rather than the order the walk
        met them.
        """

        for page in pages:
            page["directory"] = _directory_of(collection, str(page["source"]))
            page["index"] = Path(str(page["source"])).name == "index.md"
            page["node"] = False
        if not collection.parent_titles:
            return
        directories = {str(page["directory"]) for page in pages}
        for page in pages:
            if page["index"]:
                continue
            owned = f"{page['directory']}/{page['slug']}".strip("/")
            if owned in directories:
                # The Jekyll pattern of a section page beside the directory it
                # heads: `general/guidelines.md` and `general/guidelines/`. The
                # format has one node per directory, and this page is it.
                page["index"] = True
                page["directory"] = owned
        by_title = {
            (str(page["directory"]), str(page["front"].get("title") or "").strip().lower()): page
            for page in pages
        }
        for _ in range(4):
            moved = False
            for page in pages:
                parent = str(page["front"].get("parent") or "").strip().lower()
                if not parent or page["index"]:
                    continue
                owner = by_title.get((str(page["directory"]), parent))
                if owner is None or owner is page or owner["index"]:
                    # The directory's own `index.md` is already the node of the
                    # directory this page sits in; only a sibling page that is
                    # a parent creates a new one (decision D28).
                    continue
                owner["node"] = True
                page["directory"] = f"{owner['directory']}/{owner['slug']}".strip("/")
                moved = True
            if not moved:
                break

    def _pages(self, collection: Collection, directory: Path) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for path in sorted(self._candidates(collection, directory)):
            source = path.relative_to(self.root).as_posix()
            if self._is_ignored(source) or path.name.startswith("."):
                continue
            front, body = read_front_matter(path.read_text(encoding="utf-8"))
            if front is None:
                self.report.refuse(source, "3.2", "a document carries front matter")
                self.report.record(source, "refused")
                self.touched.add(source)
                continue
            name = path.name
            if collection.layout == "tree" and name == "index.md":
                # The directory is the node; the file only carries it.
                name = path.parent.name or collection.target
            if collection.layout == "item" and name == "index.md":
                # An item directory the conversion already made: its slug is
                # the directory, not the file. This is what keeps a second run
                # from nesting `articles/index/index.md`.
                name = path.parent.name
            found.append(
                {
                    "source": source,
                    "path": path,
                    "front": front,
                    "body": body,
                    "slug": _slug_of(name, collection),
                }
            )
        return found

    def _candidates(self, collection: Collection, directory: Path) -> list[Path]:
        """Every markdown file of the collection, hidden trees excluded."""

        roots = [directory / name for name in collection.roots] if collection.roots else [directory]
        found: list[Path] = []
        for root in roots:
            if root.is_file():
                found.append(root)
                continue
            if not root.is_dir():
                self.report.refuse(
                    root.relative_to(self.root).as_posix(),
                    "3.1",
                    "the profile names it and it is not there",
                )
                continue
            for path in root.glob("**/*.md"):
                # Hidden and underscore names are invisible below the
                # collection root (section 3.2). The root itself may be one:
                # `_wiki/` and `_people/` are exactly what this converts.
                if any(part.startswith((".", "_")) for part in path.relative_to(root).parts):
                    continue
                found.append(path)
        return found

    def _is_ignored(self, source: str) -> bool:
        return any(Path(source).match(pattern) for pattern in self.profile.ignore)

    def _convert_page(
        self,
        collection: Collection,
        page: Mapping[str, Any],
        titles: Mapping[str, str],
        slugs: set[str],
        landing: dict[str, str],
    ) -> None:
        source = str(page["source"])
        slug = str(page["slug"])
        if not SLUG_OK.match(slug):
            raise Refused("3.4", f"the name does not reduce to a slug: {slug!r}")
        target = self._target(collection, page, slug)
        if target in landing:
            raise Refused("3.4", f"two files land on {target}: this one and {landing[target]}")
        landing[target] = source
        page = {**page, "target": target}
        values, details = self._values(collection, page, target, titles, slugs)
        body, body_details = self._body(collection, page, titles, slugs)
        text = write_front_matter(values, body)
        self._put(source, target, text, [*details, *body_details])

    def _target(self, collection: Collection, page: Mapping[str, Any], slug: str) -> str:
        if collection.layout == "item":
            return f"{collection.target}/{slug}/index.md"
        if collection.layout == "tree":
            directory = str(page.get("directory") or "")
            if page.get("index"):
                name = "index.md"
            elif page.get("node"):
                name = f"{slug}/index.md"
            else:
                name = f"{slug}.md"
            return "/".join(part for part in (collection.target, directory, name) if part)
        return f"{collection.target}/{slug}.md"

    # -- one page's keys -----------------------------------------------------

    def _values(
        self,
        collection: Collection,
        page: Mapping[str, Any],
        target: str,
        titles: Mapping[str, str],
        slugs: set[str],
    ) -> tuple[dict[str, Any], list[str]]:
        data = dict(page["front"])
        details: list[str] = []
        for old, new in collection.rename.items():
            if old in data and new not in data:
                data[new] = data.pop(old)
                details.append(f"{old} -> {new}")
        links = self._links(collection, data, details)
        if links:
            data["links"] = links
        if collection.date_from_name:
            data["date"] = self._date(page, data, details)
        for name in collection.title_references:
            if name in data:
                data[name] = self._typed(page, name, data[name], titles, "title")
                details.append(f"{name}: titles -> {collection.kind}: references")
        for name in collection.slug_references:
            if name in data:
                data[name] = self._typed(
                    page, name, data[name], {slug: slug for slug in slugs}, "slug"
                )
                details.append(f"{name}: slugs -> {collection.kind}: references")
        image = str(data.get("image") or "").strip()
        if image:
            data["image"] = self._asset(collection, image, target, details)
        if not data.get("content_id"):
            data["content_id"] = str(uuid.uuid5(self.namespace, target))
            details.append(f"minted content_id from the repository namespace and {target}")
        if not str(data.get("title") or "").strip():
            raise Refused("3.3", "required key title is missing")
        known = {*CORE_ORDER, *collection.keep, *collection.rename.values(), "extra", "links"}
        known |= set(collection.title_references) | set(collection.slug_references)
        extra = dict(data.get("extra") or {})
        for name in list(data):
            if name in known:
                continue
            if name in collection.drop:
                details.append(f"dropped {name}: {data[name]!r}")
                data.pop(name)
                continue
            extra[name] = data.pop(name)
            details.append(f"{name} -> extra")
        if extra:
            data["extra"] = extra
        return ordered(data, (*CORE_ORDER, "links", "related", "extra")), details

    def _asset(self, collection: Collection, value: str, target: str, details: list[str]) -> str:
        """An asset reference after its directory moved, relative to the item."""

        if value.startswith("https://"):
            return value
        if value != value.strip() or " " in value.split("/")[-1].strip():
            raise Refused("3.6", f"the asset path carries a stray space: {value!r}")
        moved = value.lstrip("/")
        for source, destination in collection.assets.items():
            if moved.startswith(f"{source}/"):
                moved = f"{destination}/{moved[len(source) + 1 :]}"
                break
        else:
            # Not a directory the collection moves. It is still a repository
            # path when its first segment is one the profile names; anything
            # else is relative to the file and stays as it was written.
            if moved.split("/")[0] not in collection.absolute_roots:
                return value
        relative = _relative_to(moved, target)
        if relative != value:
            details.append(f"image: {value!r} -> {relative!r}")
        return relative

    def _links(
        self, collection: Collection, data: dict[str, Any], details: list[str]
    ) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for label, name in collection.link_keys.items():
            value = data.pop(name, None)
            if not value:
                continue
            url = _profile_url(label, str(value).strip())
            if url.startswith("http://"):
                raise Refused("3.8", f"{name} is an http:// URL and the format takes https only")
            found.append({"label": label, "url": url})
            details.append(f"{name} -> links/{label}")
        return found

    def _date(self, page: Mapping[str, Any], data: Mapping[str, Any], details: list[str]) -> str:
        written = data.get("date")
        if written:
            return str(written)[:10]
        match = DATE_NAME.match(Path(str(page["source"])).name)
        if match is None:
            raise Refused("3.3", "required key date is missing and the name carries none")
        century = match.group("century") or "20"
        found = f"{century}{match.group('year')}-{match.group('month')}-{match.group('day')}"
        details.append(f"took date from the file name: {found}")
        return found

    def _typed(
        self,
        page: Mapping[str, Any],
        name: str,
        value: Any,
        index: Mapping[str, str],
        what: str,
    ) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise Refused("3.7", f"{name} is a list of {what}s")
        found: list[str] = []
        for entry in value:
            written = str(entry).strip()
            slug = index.get(written.lower()) or index.get(written)
            if slug is None and written in self.known_slugs:
                # A `related:` list that mixes titles and slugs, which the
                # podwiki does. A slug that names a page resolves as itself.
                slug = written
            if slug is None:
                raise Refused(
                    "3.7", f"{name} names {entry!r} and no page of this collection has that {what}"
                )
            found.append(f"wiki:{slug}")
        return found

    # -- one page's body -----------------------------------------------------

    def _body(
        self,
        collection: Collection,
        page: Mapping[str, Any],
        titles: Mapping[str, str],
        slugs: set[str],
    ) -> tuple[str, list[str]]:
        body, embeds = _youtube_embeds(str(page["body"]))
        _check_fences(body)
        details: list[str] = []
        if embeds:
            details.append(f"youtube.html include -> embed fence: {embeds}")
        title = str(page["front"].get("title") or "")
        body, removed = _strip_leading_h1(body, title)
        if removed:
            details.append("removed the leading H1 that repeats the title")
        lines = body.split("\n")
        out: list[str] = []
        fence: str | None = None
        counts = dict.fromkeys(("kramdown", "relative_url", "wikilink", "style", "del"), 0)
        for line in lines:
            match = FENCE.match(line)
            if fence is not None:
                out.append(line)
                if match is not None and match.group(2).startswith(fence):
                    fence = None
                continue
            if match is not None:
                fence = match.group(2)
                out.append(line)
                continue
            if KRAMDOWN_LINE.match(line):
                counts["kramdown"] += 1
                continue
            line, count = KRAMDOWN_INLINE.subn("", line)
            counts["kramdown"] += count
            line, count = RELATIVE_URL.subn(lambda found: self._url(found, page), line)
            counts["relative_url"] += count
            line, count = SITE_BASEURL.subn(lambda found: self._url(found, page), line)
            counts["relative_url"] += count
            line, count = STYLE_ATTRIBUTE.subn("", line)
            counts["style"] += count
            line, count = STRIKETHROUGH.subn(r"<del>\1</del>", line)
            counts["del"] += count
            line, count = self._absolute(collection, line, page)
            counts["relative_url"] += count
            for token in WIKILINK.findall(line):
                slug = titles.get(token.strip().lower()) or (
                    token.strip() if token.strip() in slugs else None
                )
                if slug is None:
                    raise Refused(
                        "3.7", f"[[{token}]] names no page of this collection and is not rewritten"
                    )
                line = line.replace(f"[[{token}]]", f"[{token}]({collection.kind}:{slug})")
                counts["wikilink"] += 1
            if LIQUID.search(INLINE_CODE.sub("", line)):
                # Liquid inside code is text (section 4.1) and stays.
                raise Refused("4.1", f"Liquid this conversion does not read: {line.strip()[:80]}")
            out.append(line)
        for name, count in counts.items():
            if count:
                details.append(f"{name}: {count}")
        return "\n".join(out), details

    def _absolute(
        self, collection: Collection, line: str, page: Mapping[str, Any]
    ) -> tuple[str, int]:
        """Rewrite the absolute destinations this collection owns, and no other.

        A site path the collection serves becomes a link to the file that
        serves it, and an absolute reference into a repository directory the
        profile names becomes a relative one. Anything else is left alone, so
        `check_content` reports it rather than the conversion guessing.
        """

        target = str(page["target"])
        count = 0

        def replace(found: re.Match[str]) -> str:
            nonlocal count
            destination, _, fragment = found.group("path").partition("#")
            resolved = self.urls.get(destination.rstrip("/") + "/")
            if resolved is None and destination.split("/")[1:2]:
                root = destination.split("/")[1]
                if root in collection.absolute_roots:
                    resolved = destination.lstrip("/")
            if resolved is None:
                return found.group(0)
            count += 1
            closing = ")" if found.group(0).endswith(")") else ""
            written = _relative_to(resolved, target)
            written = f"{written}#{fragment}" if fragment else written
            return f"{found.group('open')}{written}{closing}"

        line = ABSOLUTE_LINK.sub(replace, line)
        return ABSOLUTE_SRC.sub(replace, line), count

    def _url(self, found: re.Match[str], page: Mapping[str, Any]) -> str:
        """One Liquid site path as the relative file link the format wants.

        A path the collection serves becomes a link to the file that serves it;
        a path it does not is left as the site path, which `check_content`
        reports as an absolute link, so nothing is quietly rewritten to a page
        that does not exist.
        """

        path = found.group("path")
        target = self.urls.get(path.rstrip("/") + "/")
        if target is None:
            return path
        return _relative_to(target, str(page["target"]))

    # -- data files and assets -----------------------------------------------

    def _convert_yaml_collection(self, collection: Collection) -> None:
        """Rewrite YAML manifests in place. Pages next to them stay unread."""

        name = collection.manifest
        if not name:
            self.report.refuse(
                collection.source, "3.2", "a yaml collection names the manifest file"
            )
            return
        directory = self.root / collection.source
        if not directory.is_dir():
            self.report.refuse(
                collection.source, "3.1", "the profile names a directory that is not there"
            )
            return
        found = False
        for path in sorted(directory.glob(f"**/{name}")):
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue
            source = path.relative_to(self.root).as_posix()
            if self._is_ignored(source):
                continue
            found = True
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                self.report.refuse(source, "3.2", "a manifest is a mapping")
                self.report.record(source, "refused")
                self.touched.add(source)
                continue
            values, details = self._yaml_values(collection, loaded)
            self._put(source, source, dump_yaml(values), details)
        if not found:
            self.report.refuse(
                collection.source, "3.1", f"no {name} files under the collection root"
            )

    def _yaml_values(
        self, collection: Collection, loaded: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        data = dict(loaded)
        details: list[str] = []
        for old, new in collection.rename.items():
            if old in data:
                data[new] = data.pop(old)
                details.append(f"{old} -> {new}")
        known = {*CORE_ORDER, *collection.keep, *collection.rename.values(), "extra"}
        extra = dict(data.get("extra") or {})
        for name in list(data):
            if name in known:
                continue
            if name in collection.drop:
                details.append(f"dropped {name}: {data[name]!r}")
                data.pop(name)
                continue
            extra[name] = data.pop(name)
            details.append(f"{name} -> extra")
        if extra:
            data["extra"] = extra
        return ordered(data, (*CORE_ORDER, "extra")), details

    def _move_verbatim(self, collection: Collection, directory: Path) -> None:
        """Move a collection whose files the conversion does not read.

        A `data` file is opaque by section 3.8 and the FAQ is opaque by
        decision D26. Either way the bytes are carried across unchanged, which
        is the strongest form of the promise this script makes.
        """

        suffixes = (".yaml", ".yml", ".json") if collection.layout == "data" else None
        for path in sorted(directory.glob("**/*")):
            if not path.is_file():
                continue
            if suffixes is not None and path.suffix not in suffixes:
                continue
            source = path.relative_to(self.root).as_posix()
            rel = path.relative_to(directory).as_posix()
            target = f"{collection.target}/{path.name if suffixes else rel}"
            self.copies.append((source, target))
            self.report.record(source, "renamed", target=target, details=["carried across unread"])
            self.touched.add(source)

    def _move_assets(self, source: str, target: str) -> None:
        directory = self.root / source
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("**/*")):
            if not path.is_file():
                continue
            rel = path.relative_to(directory).as_posix()
            old = path.relative_to(self.root).as_posix()
            self.copies.append((old, f"{target}/{rel}"))
            self.report.record(old, "renamed", target=f"{target}/{rel}")
            self.touched.add(old)

    # -- writing -------------------------------------------------------------

    def _put(self, source: str, target: str, text: str, details: Sequence[str]) -> None:
        existing = self.root / target
        if source == target:
            if existing.read_text(encoding="utf-8") == text:
                self.report.record(source, "unchanged")
            else:
                self.writes.append((target, text))
                self.report.record(source, "rewritten", details=details)
            self.touched.add(source)
            return
        self.writes.append((target, text))
        self.removals.append(source)
        self.report.record(source, "renamed", target=target, details=details)
        self.touched.add(source)

    def _write_manifest(self) -> None:
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "collections": [
                {"kind": item.kind, "path": item.target} for item in self.profile.collections
            ],
        }
        if self.profile.ignore:
            manifest["ignore"] = list(self.profile.ignore)
        if self.profile.strict_references is not None:
            manifest["strict_references"] = self.profile.strict_references
        if self.profile.theme_pairs:
            manifest["theme_pairs"] = True
        text = dump_yaml(manifest)
        existing = self.root / MANIFEST_NAME
        if existing.is_file() and existing.read_text(encoding="utf-8") == text:
            self.report.record(MANIFEST_NAME, "unchanged")
        else:
            self.writes.append((MANIFEST_NAME, text))
            self.report.record(MANIFEST_NAME, "created" if not existing.is_file() else "rewritten")
        self.touched.add(MANIFEST_NAME)

    def _account(self) -> None:
        for path in sorted(self.report.before):
            if path not in self.touched:
                self.report.record(path, "unchanged")

    def _flush(self) -> None:
        if not self.apply:
            return
        for source, target in self.copies:
            destination = self.root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.root / source).read_bytes())
            (self.root / source).unlink()
        for path, text in self.writes:
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        for path in self.removals:
            target = self.root / path
            if target.is_file():
                target.unlink()
        _prune(self.root)


# --- helpers ------------------------------------------------------------------


def _slug_of(name: str, collection: Collection) -> str:
    stem = name[:-3] if name.endswith(".md") else name
    if stem == "index":
        return "index"
    stem = DATE_NAME.sub("", stem) if collection.date_from_name else stem
    return ORDER_PREFIX.sub("", stem)


YOUTUBE_INCLUDE = re.compile(
    r'^\s*\{%\s*include\s+youtube\.html\s+video_id="(?P<id>[^"]+)"\s*%\}\s*$', re.MULTILINE
)


def _youtube_embeds(body: str) -> tuple[str, int]:
    """`FORMAT.md` section 4.3: the one include the format has a shape for."""

    def replace(found: re.Match[str]) -> str:
        return f"```embed\ntype: youtube\nid: {found.group('id')}\n```"

    return YOUTUBE_INCLUDE.subn(replace, body)


def _check_fences(body: str) -> None:
    """Refuse a body whose last code fence is never closed.

    Everything after an unterminated fence is code to the renderer and to this
    conversion alike, so a link inside it is not rewritten and a construct
    inside it is not seen. Converting such a file would silently leave half of
    it as it was; the author closes the fence first.
    """

    fence: str | None = None
    for line in body.split("\n"):
        match = FENCE.match(line)
        if fence is None:
            if match is not None:
                fence = match.group(2)
        elif match is not None and match.group(2).startswith(fence):
            fence = None
    if fence is not None:
        raise Refused("4.1", f"a {fence} code fence is opened and never closed")


def _directory_of(collection: Collection, source: str) -> str:
    parent = Path(source).parent.as_posix()
    if parent in (".", collection.source):
        return ""
    if collection.source not in (".", "") and parent.startswith(f"{collection.source}/"):
        return parent[len(collection.source) + 1 :]
    return parent


def _jekyll_urls(collection: Collection, pages: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """`{site path: target file}` for every page, as Jekyll served it."""

    found: dict[str, str] = {}
    for page in pages:
        source = str(page["source"])
        stem = source[:-3]
        if collection.source not in (".", "") and stem.startswith(f"{collection.source}/"):
            stem = stem[len(collection.source) + 1 :]
        if stem.endswith("/index"):
            stem = stem[: -len("/index")]
        directory = str(page.get("directory") or "")
        name = str(page["slug"])
        target = "/".join(part for part in (collection.target, directory, f"{name}.md") if part)
        if page.get("index"):
            target = "/".join(part for part in (collection.target, directory, "index.md") if part)
        elif page.get("node"):
            target = "/".join(
                part for part in (collection.target, directory, name, "index.md") if part
            )
        found[f"{collection.url_prefix}/{stem}/".replace("//", "/")] = target
    return found


def _relative_to(target: str, source: str) -> str:
    """`target` written relative to the directory `source` sits in."""

    base = Path(source).parent.parts
    parts = Path(target).parts
    shared = 0
    while shared < min(len(base), len(parts) - 1) and base[shared] == parts[shared]:
        shared += 1
    up = [".."] * (len(base) - shared)
    return "/".join([*up, *parts[shared:]]) or target


def _profile_url(label: str, value: str) -> str:
    if value.startswith("http"):
        return value
    return {
        "linkedin": f"https://www.linkedin.com/in/{value}/",
        "github": f"https://github.com/{value}",
        "x": f"https://x.com/{value}",
        "youtube": f"https://www.youtube.com/@{value}",
    }.get(label, value)


def _strip_leading_h1(body: str, title: str) -> tuple[str, bool]:
    stripped = body.lstrip("\n")
    first, _, rest = stripped.partition("\n")
    if not first.startswith("# ") or first[2:].strip().lower() != title.strip().lower():
        return body, False
    return rest.lstrip("\n"), True


def _prune(root: Path) -> None:
    """Remove the directories a rename emptied, and nothing else."""

    for path in sorted(root.glob("**/*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


# --- the command line ---------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m community_base.content_sync.convert.documents",
        description="Convert a document collection to the content format, in place.",
    )
    parser.add_argument("path", help="the repository to convert")
    parser.add_argument("--profile", required=True, choices=sorted(PROFILES), help="the repository")
    parser.add_argument("--dry-run", action="store_true", help="run every rule and write nothing")
    options = parser.parse_args(argv)
    report = convert_documents(
        Path(options.path), PROFILES[options.profile], apply=not options.dry_run
    )
    sys.stdout.write(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
