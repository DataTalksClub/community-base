"""The shared knowledge base: wiki pages, documentation pages and people.

One page model serves both sections. A wiki page is a flat, standalone page
(``parent`` is null and must stay null). A documentation page may point at
another documentation page through ``parent`` to form the documentation tree;
``nav_order`` positions it among its siblings. ``Person`` is the record the
``person`` kind fills and the target the ``authors``, ``instructors`` and
``guests`` reference keys resolve to (``content_sync/FORMAT.md`` sections 3.7
and 3.8); decision D31 makes it an optional instructor source, so a site
decides whether to use it. This app owns storage, hierarchy resolution,
rendering and the search corpus. The package parsers for the three kinds live
in ``content_sync_parsers``; a site still owns its public templates, and a site
that fills the model from its own shapes still owns that parser (D16, D24).
"""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from community_base.content_sync.kinds.person import LINK_LABELS
from community_base.content_sync.provenance import SourceProvenanceMixin, provenance_constraint
from community_base.content_sync.rendering import (
    render_markdown,
    sanitize_rendered_html,
    strip_leading_title_h1,
)
from community_base.knowledge_base.routes import PERSON_KIND, default_public_path

SECTION_WIKI = "wiki"
SECTION_DOCS = "docs"
SECTION_CHOICES = (
    (SECTION_WIKI, "Wiki"),
    (SECTION_DOCS, "Documentation"),
)
STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_CHOICES = (
    (STATUS_DRAFT, "Draft"),
    (STATUS_PUBLISHED, "Published"),
)
BODY_HTML_MARKDOWN = "markdown"
BODY_HTML_SITE = "site"
BODY_HTML_SOURCE_CHOICES = (
    (BODY_HTML_MARKDOWN, "Rendered from the markdown body"),
    (BODY_HTML_SITE, "Supplied by the site"),
)

SLUG_MAX_LENGTH = 300
TITLE_MAX_LENGTH = 300
PUBLIC_PATH_MAX_LENGTH = 500

# The donor slug alphabets (DTC wiki `[A-Za-z0-9._-]`, docs path segments) both
# carry dots, so a segment is one step wider than Django's ``validate_slug``.
# A slug may also be several such segments joined by ``/``: a site whose page
# identity is a path (DTC's docs stable key) stores the whole path as the slug,
# while a site whose identity is a leaf segment (AISL) stores one segment and
# lets ``parent`` carry the path. Neither a leading, trailing nor doubled ``/``
# is a segment, so both shapes stay unambiguous.
SLUG_SEGMENT_PATTERN = r"[-a-zA-Z0-9_.]+"
SLUG_PATTERN = rf"^{SLUG_SEGMENT_PATTERN}(?:/{SLUG_SEGMENT_PATTERN})*$"
slug_validator = RegexValidator(
    SLUG_PATTERN,
    "Enter a slug: letters, digits, dots, dashes or underscores, "
    "optionally in several segments joined by a slash.",
)


# A site-owned public path is a root-relative URL path: no scheme, no host,
# no query and no fragment, so it can be written into a template as-is.
PUBLIC_PATH_PATTERN = r"^/[^\s?#]*$"
public_path_validator = RegexValidator(
    PUBLIC_PATH_PATTERN,
    "Enter a root-relative path starting with a slash, without whitespace, query or fragment.",
)


CONTENT_SOURCE = "cb_content_sync.ContentSource"


def source_field(related_name: str):
    """The row's content source: what ``delete_missing`` scopes ownership by.

    Named by a foreign key, not by ``source_content_id``, which the format
    reserves for the item's own ``content_id``
    (``content_sync/FORMAT.md`` section 3.4). Deleting a source leaves its
    content in place and unowned rather than deleting rows, which is what the
    dangling identifier this field replaced did in practice.
    """

    return models.ForeignKey(
        CONTENT_SOURCE,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name=related_name,
        help_text="The content source this row was synced from. Null for Studio-authored rows.",
    )


class RenderedBodyModel(models.Model):
    """A markdown body with its rendered HTML, and who rendered it.

    At ``markdown``, the default, ``save`` renders the body with the one
    package renderer. At ``site`` it stops rendering and keeps what it was
    handed, sanitized: a site with its own pipeline and a sync parser that
    renders at sync time both need that. One implementation serves every
    record of this app that carries a body.
    """

    body = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="", editable=False)
    body_html_source = models.CharField(
        max_length=20,
        choices=BODY_HTML_SOURCE_CHOICES,
        default=BODY_HTML_MARKDOWN,
        help_text=(
            "Where body_html comes from: this app's markdown renderer, or the site. "
            "Site-supplied HTML is sanitized on every save but never re-rendered."
        ),
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.body_html_source == BODY_HTML_SITE:
            # The site owns the rendering, not the trust: supplied HTML goes
            # through the same sanitizer as rendered markdown. Sanitizing is
            # idempotent, so a re-save leaves stored HTML byte for byte alone.
            if update_fields is None or "body_html" in set(update_fields):
                self.body_html = sanitize_rendered_html(self.body_html)
        else:
            self.body_html = render_markdown(strip_leading_title_h1(self.body, self.title))
            if update_fields is not None:
                update_fields = set(update_fields)
                if "body" in update_fields:
                    update_fields.add("body_html")
                kwargs["update_fields"] = list(update_fields)
        super().save(*args, **kwargs)

    def set_site_rendered_html(self, rendered_html: str) -> None:
        """Hand the record already-rendered HTML instead of markdown.

        The app stops rendering this body: ``save`` sanitizes what the site
        produced and stores it unchanged. Pass an empty string, or set
        ``body_html_source`` back to ``markdown``, to return the record to the
        app's renderer.
        """

        self.body_html_source = BODY_HTML_SITE
        self.body_html = rendered_html


class KnowledgeBasePage(SourceProvenanceMixin, RenderedBodyModel):
    """One wiki or documentation page, with its rendered HTML stored alongside.

    ``slug`` is the site's stable key among its siblings: unique per
    ``(section, parent)``, not per section, so the same leaf segment may
    appear under different parents (DTC's documentation tree repeats
    ``project`` seven times). A site whose identity is the whole path may
    store the path as the slug instead. ``parent`` is only meaningful for
    documentation pages: wiki pages are a flat set and must leave it null.

    ``record`` is the row's section-shaped metadata. The package stores it
    opaquely: it never reads a key, ships no field for one, and adds no
    per-site column. The package parsers write the format's own derived
    metadata into it (the heading list and the resolved reference list); a
    site parser owns the record of the rows it writes. DTC's wiki pages put
    ``blocks``, ``tags``, ``fragment_ids``, ``unresolved_fragment_ids`` and
    ``relations`` there; its documentation pages put ``edit_url``,
    ``has_toc``, ``permalink`` and the rest of their projection record.

    ``source`` names the content source the row was synced from and is the
    ownership scope of ``sync.delete_missing``. ``source_content_id`` holds
    the item's own ``content_id`` and nothing else, as the format requires.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, default=SECTION_DOCS)
    slug = models.CharField(max_length=SLUG_MAX_LENGTH, validators=[slug_validator])
    title = models.CharField(max_length=TITLE_MAX_LENGTH)
    summary = models.TextField(blank=True, default="")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Documentation tree parent. Wiki pages must leave this null.",
    )
    nav_order = models.IntegerField(
        default=0,
        help_text="Position among siblings; ties break by title, then slug.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PUBLISHED)
    record = models.JSONField(
        blank=True,
        default=dict,
        help_text=(
            "Section-shaped metadata. The package stores and returns it and never reads a "
            "key of it; put parser-owned and site-specific fields here, not in new columns."
        ),
    )
    source = source_field("knowledge_base_pages")
    public_path = models.CharField(  # noqa: DJ001 -- null means "derive from the tree".
        max_length=PUBLIC_PATH_MAX_LENGTH,
        null=True,
        blank=True,
        default=None,
        validators=[public_path_validator],
        help_text=(
            "Site-owned public URL path. Null derives the path from the ancestor chain, "
            "which is what a site that does not own its routes wants."
        ),
    )

    class Meta:
        ordering = ("section", "slug")
        constraints = [
            # A NULL parent does not compare equal to itself in a unique index,
            # so the root level needs its own conditional constraint; without
            # it two root pages could share a slug within one section.
            models.UniqueConstraint(
                fields=("section", "parent", "slug"),
                condition=models.Q(parent__isnull=False),
                name="cb_kb_page_child_slug_unique",
            ),
            models.UniqueConstraint(
                fields=("section", "slug"),
                condition=models.Q(parent__isnull=True),
                name="cb_kb_page_root_slug_unique",
            ),
            # Two pages cannot answer at one URL. Null paths do not collide.
            models.UniqueConstraint(
                fields=("public_path",),
                condition=models.Q(public_path__isnull=False),
                name="cb_kb_page_public_path_unique",
            ),
            # ``source_content_id`` is the item's own ``content_id`` and is
            # absent on a row whose parser does not write one, so it is not
            # part of the all-or-nothing set.
            provenance_constraint(name="cb_kb_page_source_complete", identity_fields=()),
        ]
        indexes = [
            models.Index(
                fields=("section", "status"),
                name="cb_kb_section_status_idx",
            ),
        ]

    SOURCE_IDENTITY_FIELDS = ()

    def __str__(self):
        return f"{self.get_section_display()}: {self.title}"

    def save(self, *args, **kwargs):
        if not self.public_path:
            self.public_path = None
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        """The page's public path: the site's own when it stored one.

        A site whose public paths come from the source files (DTC derives
        them from the documentation file path, independently of the parent
        links) stores ``public_path``; a site that leaves it null keeps the
        ancestor-chain path this app has always built.
        """

        if self.public_path:
            return self.public_path
        parts = (*self.ancestor_slugs(), self.slug)
        return f"/{self.section}/" + "/".join(parts) + "/"

    def clean(self):
        super().clean()
        if not self.public_path:
            self.public_path = None
        errors: dict[str, str] = {}
        if not isinstance(self.record, dict):
            errors["record"] = "The record must be a JSON object, so sites can add keys to it."
        if self.section == SECTION_WIKI and self.parent_id is not None:
            errors["parent"] = "Wiki pages are a flat set; a wiki page cannot have a parent."
        if self.parent_id is not None:
            if self.pk is not None and self.parent_id == self.pk:
                errors["parent"] = "A page cannot be its own parent."
            else:
                if self.parent.section != self.section:
                    errors["parent"] = "A parent page must belong to the same section."
                elif self._has_ancestor_cycle():
                    errors["parent"] = "A page cannot be its own ancestor."
        if errors:
            raise ValidationError(errors)

    def _has_ancestor_cycle(self) -> bool:
        seen = {self.pk}
        current = self.parent
        while current is not None:
            if current.pk in seen:
                return True
            seen.add(current.pk)
            current = current.parent
        return False

    @property
    def is_published(self):
        return self.status == STATUS_PUBLISHED

    @property
    def has_children(self):
        return self.children.exists()

    def ancestor_slugs(self) -> list[str]:
        """Return the ancestor slugs from the section root down to the parent.

        One query per level; page trees are shallow (the studio detail screen
        caps its walk at the same depth), so this stays cheap in practice.
        """

        slugs: list[str] = []
        seen = {self.pk}
        current = self
        while current.parent_id is not None and len(slugs) < 20:
            current = current.parent
            if current.pk in seen:
                break
            seen.add(current.pk)
            slugs.append(current.slug)
        slugs.reverse()
        return slugs


class Person(SourceProvenanceMixin, RenderedBodyModel):
    """One person: the record the ``person`` kind fills (section 3.8).

    ``title`` is the display name, ``summary`` the short bio, ``image`` the
    picture and the body the long bio; ``links`` is a list of
    ``{label, url}`` whose labels are the ones the kind declares. The record
    is the target the ``authors``, ``instructors`` and ``guests`` reference
    keys resolve to, so a document in another source can credit a person the
    package already synced (``FORMAT.md`` section 3.7).

    Decision D31 makes the kind an optional instructor source: the package
    defines the shape and ships no public route or template for it, and a
    site decides whether to fill it and where to publish it.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    slug = models.CharField(max_length=SLUG_MAX_LENGTH, unique=True, validators=[slug_validator])
    title = models.CharField(max_length=TITLE_MAX_LENGTH, help_text="The display name.")
    summary = models.TextField(blank=True, default="", help_text="The short bio.")
    image = models.CharField(
        max_length=PUBLIC_PATH_MAX_LENGTH,
        blank=True,
        default="",
        help_text="The picture, as the media store returned it.",
    )
    links = models.JSONField(
        blank=True,
        default=list,
        help_text="A list of {label, url}; the label is one of the kind's declared labels.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PUBLISHED)
    record = models.JSONField(
        blank=True,
        default=dict,
        help_text=(
            "Metadata shaped by whoever writes the row. The package stores and returns it "
            "and never reads a key of it."
        ),
    )
    source = source_field("people")

    class Meta:
        ordering = ("title", "slug")
        verbose_name_plural = "people"
        constraints = [
            provenance_constraint(name="cb_kb_person_source_complete", identity_fields=()),
        ]
        indexes = [
            models.Index(fields=("status", "slug"), name="cb_kb_person_status_idx"),
        ]

    SOURCE_IDENTITY_FIELDS = ()

    def __str__(self):
        return self.title

    def get_absolute_url(self) -> str:
        """The default route the ``person`` kind declares (section 3.4).

        The package ships no public route for people (D31), so this is the
        path a reference to this person resolves to and the path a site that
        mounts its own people routes matches.
        """

        return default_public_path(PERSON_KIND, self.slug)

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if not isinstance(self.record, dict):
            errors["record"] = "The record must be a JSON object, so sites can add keys to it."
        message = _links_defect(self.links)
        if message is not None:
            errors["links"] = message
        if errors:
            raise ValidationError(errors)

    @property
    def is_published(self):
        return self.status == STATUS_PUBLISHED


def _links_defect(value) -> str | None:
    """Why ``links`` is not a list of ``{label, url}``, or None."""

    if not isinstance(value, list):
        return "Links must be a list of {label, url} objects."
    for entry in value:
        if not isinstance(entry, dict):
            return "Links must be a list of {label, url} objects."
        if set(entry) - {"label", "url"}:
            return "A link carries a label and a url and nothing else."
        if entry.get("label") not in LINK_LABELS:
            return f"A link label is one of: {', '.join(LINK_LABELS)}."
        if not isinstance(entry.get("url"), str) or not entry["url"]:
            return "A link needs a url."
    return None
