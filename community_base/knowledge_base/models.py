"""The shared knowledge base: wiki pages and documentation pages.

One page model serves both sections. A wiki page is a flat, standalone page
(``parent`` is null and must stay null). A documentation page may point at
another documentation page through ``parent`` to form the documentation tree;
``nav_order`` positions it among its siblings. Sites fill the model with their
own ``content_sync`` parsers and render it with their own public templates;
this app owns storage, hierarchy resolution, rendering and the search corpus.
"""

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from community_base.content_sync.provenance import SourceProvenanceMixin, provenance_constraint
from community_base.curriculum.rendering import strip_leading_title_h1
from community_base.knowledge_base.rendering import render_markdown, sanitize_rendered_html

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


class KnowledgeBasePage(SourceProvenanceMixin, models.Model):
    """One wiki or documentation page, with its rendered HTML stored alongside.

    ``slug`` is the site's stable key among its siblings: unique per
    ``(section, parent)``, not per section, so the same leaf segment may
    appear under different parents (DTC's documentation tree repeats
    ``project`` seven times). A site whose identity is the whole path may
    store the path as the slug instead. ``parent`` is only meaningful for
    documentation pages: wiki pages are a flat set and must leave it null.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, default=SECTION_DOCS)
    slug = models.CharField(max_length=SLUG_MAX_LENGTH, validators=[slug_validator])
    title = models.CharField(max_length=TITLE_MAX_LENGTH)
    summary = models.TextField(blank=True, default="")
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
            provenance_constraint(name="cb_kb_page_source_complete"),
        ]
        indexes = [
            models.Index(
                fields=("section", "status"),
                name="cb_kb_section_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_section_display()}: {self.title}"

    def save(self, *args, **kwargs):
        if not self.public_path:
            self.public_path = None
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

    def set_site_rendered_html(self, rendered_html: str) -> None:
        """Hand the page already-rendered HTML instead of markdown.

        The app stops rendering this page's body: ``save`` sanitizes what the
        site produced and stores it unchanged. Pass an empty string, or set
        ``body_html_source`` back to ``markdown``, to return the page to the
        app's renderer.
        """

        self.body_html_source = BODY_HTML_SITE
        self.body_html = rendered_html

    def clean(self):
        super().clean()
        if not self.public_path:
            self.public_path = None
        errors: dict[str, str] = {}
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
