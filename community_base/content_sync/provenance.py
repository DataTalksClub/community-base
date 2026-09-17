"""App-neutral source provenance for synced content records.

Moved out of ``community_base.curriculum.models`` so apps like the
knowledge base can carry provenance on sites that do not install the
curriculum app: this module defines no concrete models, so importing it
never requires an app registry entry. ``curriculum.models`` re-exports
the mixin and constraint for compatibility with existing imports.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from community_base.curriculum.validators import (
    SHA1_PATTERN,
    SHA256_PATTERN,
    sha1_validator,
    sha256_validator,
    source_path_validator,
    validate_source_path,
)

_SHA1_BODY = SHA1_PATTERN.strip("^$")
_SHA256_BODY = SHA256_PATTERN.strip("^$")


def provenance_constraint(*, name: str, identity_fields: tuple[str, ...] = ("source_content_id",)):
    """All-or-nothing provenance: identity, path, commit and checksum move together."""

    fields = (*identity_fields, "source_path", "source_commit_sha", "source_checksum")
    absent = Q(**{f"{field}__isnull": True for field in fields})
    present = Q(**{f"{field}__isnull": False for field in fields})
    present &= Q(source_commit_sha__regex=_SHA1_BODY)
    present &= Q(source_checksum__regex=_SHA256_BODY)
    return models.CheckConstraint(condition=absent | present, name=name)


class SourceProvenanceMixin(models.Model):
    """Nullable provenance shared by source-managed records.

    ``source_content_id`` holds the item's own ``content_id`` from the content
    format: the upsert key an author writes in the file's front matter or
    manifest (``content_sync/FORMAT.md`` section 3.4). It is not the id of the
    ``ContentSource`` the item came from, and it is not a scope: a row's source
    is named by a foreign key, not by this field.

    One package app disagrees today. ``curriculum.importing`` follows the rule;
    ``knowledge_base.sync`` stores ``ContentSource.pk`` here and uses it as the
    ownership scope of ``delete_missing``. ``ContentSource.id`` and this field
    are both ``UUIDField``, so the two meanings have the same type and the
    mistake cannot raise: it produces rows whose provenance points at a source
    instead of an item. Issue C7.9c repairs the knowledge base with a source
    foreign key and a data migration; C7.7, which wrote this contract down,
    ships no migration and so could not repair it.
    """

    source_content_id = models.UUIDField(null=True, blank=True)
    source_path = models.CharField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=1024,
        null=True,
        blank=True,
        validators=[source_path_validator],
    )
    source_commit_sha = models.CharField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=40,
        null=True,
        blank=True,
        validators=[sha1_validator],
    )
    source_checksum = models.CharField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=64,
        null=True,
        blank=True,
        validators=[sha256_validator],
    )

    SOURCE_IDENTITY_FIELDS = ("source_content_id",)

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        field_names = (
            *self.SOURCE_IDENTITY_FIELDS,
            "source_path",
            "source_commit_sha",
            "source_checksum",
        )
        values = {field_name: getattr(self, field_name) for field_name in field_names}
        populated = {field_name for field_name, value in values.items() if value is not None}
        if populated and len(populated) != len(values):
            missing = sorted(set(values) - populated)
            raise ValidationError(
                {
                    field_name: "Source provenance must be supplied as a complete set."
                    for field_name in missing
                }
            )
        empty = {
            field_name
            for field_name, value in values.items()
            if value is not None and isinstance(value, str) and not value
        }
        if empty:
            raise ValidationError(
                {field_name: "Source provenance values cannot be empty." for field_name in empty}
            )
        if self.source_path:
            validate_source_path(self.source_path)
