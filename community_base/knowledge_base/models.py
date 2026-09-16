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

from community_base.curriculum.models import SourceProvenanceMixin, provenance_constraint
from community_base.curriculum.rendering import strip_leading_title_h1
from community_base.knowledge_base.rendering import render_markdown

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

SLUG_MAX_LENGTH = 300
TITLE_MAX_LENGTH = 300

# The donor slug alphabets (DTC wiki `[A-Za-z0-9._-]`, docs path segments) both
# carry dots, so this is one step wider than Django's ``validate_slug``.
SLUG_PATTERN = r"^[-a-zA-Z0-9_.]+$"
slug_validator = RegexValidator(
    SLUG_PATTERN, "Enter a slug: letters, digits, dots, dashes or underscores."
)


class KnowledgeBasePage(SourceProvenanceMixin, models.Model):
    """One wiki or documentation page, with its rendered HTML stored alongside.

    ``slug`` is the site's stable key within the section (for a documentation
    tree it is typically the source path without extension, for the wiki the
    page stem). ``parent`` is only meaningful for documentation pages: wiki
    pages are a flat set and must leave it null.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, default=SECTION_DOCS)
    slug = models.CharField(max_length=SLUG_MAX_LENGTH, validators=[slug_validator])
    title = models.CharField(max_length=TITLE_MAX_LENGTH)
    summary = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="", editable=False)
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

    class Meta:
        ordering = ("section", "slug")
        constraints = [
            models.UniqueConstraint(
                fields=("section", "slug"),
                name="cb_kb_page_section_slug_unique",
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
        self.body_html = render_markdown(strip_leading_title_h1(self.body, self.title))
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "body" in update_fields:
                update_fields.add("body_html")
            kwargs["update_fields"] = list(update_fields)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        parts = (*self.ancestor_slugs(), self.slug)
        return f"/{self.section}/" + "/".join(parts) + "/"

    def clean(self):
        super().clean()
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
