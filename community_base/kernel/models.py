"""Kernel model bases: optimistic concurrency and append-only records.

Moved from DTC ``core/models.py`` (decision D19, issue C7.5): the kernel had
no model base classes, and eleven DTC models each depended on a DTC-only
``RevisionedModel`` for the same concern, a portable compare-and-swap
mutation that behaves the same way on SQLite and deployed PostgreSQL.
``AppendOnlyManager`` is the companion base for records that must never be
rewritten or deleted once written, such as an audit trail.

Both classes are abstract or manager-only, so importing this module never
requires an app registry entry and defines no concrete model. Nothing here
needs its own migration; a site or package app only gets a migration once it
declares a concrete model that inherits ``RevisionedModel`` or points its
``objects`` manager at ``AppendOnlyManager``.

The donor's ``AppendOnlyQuerySet.update`` also let one concrete DTC model,
``AuditEvent``, null two specific foreign keys (``actor``, ``api_principal``)
through Django's ``on_delete=SET_NULL`` cascade, so a deleted user is
forgotten without rewriting the audit trail otherwise. That carve-out named
the concrete DTC model directly inside the shared queryset. It does not move
here: it is domain policy that belongs to a model that stays DTC-owned
(decision D19 explicitly excludes the eleven consuming models from this
issue), and copying it verbatim would require importing a site model into
the kernel, which the architecture forbids. The kernel's ``AppendOnlyManager``
is therefore unconditionally append-only: every ``update()``, ``delete()``,
``bulk_create()`` and ``bulk_update()`` call raises ``AppendOnlyViolation``,
with no exceptions. This is not a behaviour change for anything that moves
in this issue: none of DTC's eleven ``RevisionedModel`` subclasses use
``AppendOnlyManager``, only ``AuditEvent`` does, and ``AuditEvent`` is not
part of this move. A later issue that migrates ``AuditEvent`` onto this base
decides, from the DTC side, how to keep that allowance if it still needs it.
"""

from __future__ import annotations

from typing import Any

from django.db import models, router


class AppendOnlyViolation(RuntimeError):
    """Raised when application code attempts to rewrite immutable evidence."""


class RevisionConflict(RuntimeError):
    """Raised when a compare-and-swap mutation uses a stale revision."""

    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"stale revision: expected {expected}, current revision is {actual}")


class AppendOnlyQuerySet(models.QuerySet[Any]):
    def update(self, **kwargs: Any) -> int:
        raise AppendOnlyViolation("append-only records cannot be updated")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise AppendOnlyViolation("append-only records cannot be deleted")

    def bulk_create(self, *args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        raise AppendOnlyViolation("append-only records must be inserted through their writer")

    def bulk_update(self, *args: Any, **kwargs: Any) -> int:
        del args, kwargs
        raise AppendOnlyViolation("append-only records cannot be updated")


class AppendOnlyManager(models.Manager.from_queryset(AppendOnlyQuerySet)):  # type: ignore[misc]
    pass


class RevisionedModel(models.Model):
    revision = models.PositiveBigIntegerField(default=1)

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Use one portable conditional update for revisioned service mutations.

        Callers increment ``revision`` and include it in ``update_fields``. The
        update succeeds only while the persisted row still has the immediately
        preceding revision, so SQLite and deployed PostgreSQL exercise the same
        optimistic compare-and-swap contract.
        """

        update_fields = kwargs.get("update_fields")
        if self._state.adding or update_fields is None or "revision" not in update_fields:
            super().save(*args, **kwargs)
            return
        if args or kwargs.get("force_insert"):
            raise ValueError(
                "revisioned conditional updates do not support positional/insert flags"
            )
        if self.revision < 2:
            raise ValueError("revisioned updates must increment revision exactly once")

        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        values: dict[str, Any] = {}
        for field_name in update_fields:
            field = self._meta.get_field(field_name)
            if not isinstance(field, models.Field) or field.primary_key:
                raise ValueError("revisioned update_fields must name concrete non-key fields")
            value = field.pre_save(self, add=False)
            values[field.attname] = value

        expected_revision = self.revision - 1
        queryset = (
            type(self)
            ._default_manager.using(using)
            .filter(
                pk=self.pk,
                revision=expected_revision,
            )
        )
        if queryset.update(**values) != 1:
            actual_revision = (
                type(self)
                ._default_manager.using(using)
                .filter(pk=self.pk)
                .values_list("revision", flat=True)
                .first()
            )
            if actual_revision is None:
                raise type(self).DoesNotExist(self.pk)
            raise RevisionConflict(expected=expected_revision, actual=actual_revision)
        self._state.db = using
