"""Document conversion declarations shared by its single-purpose owners."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

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

DATE_NAME = re.compile(r"^(?:(?P<century>\d{2})?(?P<year>\d{2})-(?P<month>\d{2})-(?P<day>\d{2}))-")

SLUG_OK = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

ORDER_PREFIX = re.compile(r"^\d{2,3}-(?=.)")


class Refused(Exception):
    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


@dataclass(frozen=True)
class Collection:
    """One collection of one repository, and the rules it converts under."""

    kind: str
    source: str
    target: str
    layout: str = "flat"
    rename: Mapping[str, str] = field(default_factory=dict)
    drop: tuple[str, ...] = ()
    keep: tuple[str, ...] = ()
    title_references: tuple[str, ...] = ()
    slug_references: tuple[str, ...] = ()
    link_keys: Mapping[str, str] = field(default_factory=dict)
    manifest: str = ""
    date_from_name: bool = False
    assets: Mapping[str, str] = field(default_factory=dict)
    parent_titles: bool = False
    jekyll_urls: bool = False
    url_prefix: str = ""
    absolute_roots: tuple[str, ...] = ()
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
        collections=(Collection(kind="faq", source="_questions", target="faq", layout="opaque"),),
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
