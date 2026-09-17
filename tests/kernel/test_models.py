import pytest
from django.db import models

from community_base.kernel.models import (
    AppendOnlyViolation,
    RevisionConflict,
    RevisionedModel,
)
from testproject.models import FixtureAppendOnlyRecord, FixtureRevisionedRecord

pytestmark = pytest.mark.django_db


class TestRevisionedModel:
    def test_create_bypasses_the_conditional_path(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        assert record.revision == 1
        assert FixtureRevisionedRecord.objects.get(pk=record.pk).label == "first"

    def test_conditional_save_advances_revision_when_not_stale(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        record.label = "second"
        record.revision = 2
        record.save(update_fields=["label", "revision"])

        stored = FixtureRevisionedRecord.objects.get(pk=record.pk)
        assert stored.label == "second"
        assert stored.revision == 2

    def test_concurrent_write_raises_conflict_and_does_not_silently_overwrite(self):
        """Two racing writers load the same row; the loser must not win silently.

        This is the behaviour the base class exists for: a second writer that
        started from the same revision as the first must be told it lost the
        race, and the winner's write must survive untouched.
        """

        original = FixtureRevisionedRecord.objects.create(label="first")
        writer_a = FixtureRevisionedRecord.objects.get(pk=original.pk)
        writer_b = FixtureRevisionedRecord.objects.get(pk=original.pk)

        writer_a.label = "writer-a"
        writer_a.revision = 2
        writer_a.save(update_fields=["label", "revision"])

        writer_b.label = "writer-b"
        writer_b.revision = 2
        with pytest.raises(RevisionConflict) as caught:
            writer_b.save(update_fields=["label", "revision"])

        assert caught.value.expected == 1
        assert caught.value.actual == 2

        stored = FixtureRevisionedRecord.objects.get(pk=original.pk)
        assert stored.label == "writer-a"
        assert stored.revision == 2

    def test_missing_row_raises_does_not_exist(self):
        record = FixtureRevisionedRecord.objects.create(label="first")
        FixtureRevisionedRecord.objects.filter(pk=record.pk).delete()

        record.label = "second"
        record.revision = 2
        with pytest.raises(FixtureRevisionedRecord.DoesNotExist):
            record.save(update_fields=["label", "revision"])

    def test_update_fields_without_revision_uses_plain_save(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        record.label = "second"
        record.save(update_fields=["label"])

        stored = FixtureRevisionedRecord.objects.get(pk=record.pk)
        assert stored.label == "second"
        assert stored.revision == 1

    def test_revision_below_two_is_rejected_on_conditional_path(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        record.revision = 1
        with pytest.raises(ValueError, match="exactly once"):
            record.save(update_fields=["revision"])

    def test_positional_args_are_rejected_on_conditional_path(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        record.revision = 2
        with pytest.raises(ValueError, match="positional/insert"):
            record.save(False, update_fields=["revision"])

    def test_force_insert_is_rejected_on_conditional_path(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        record.revision = 2
        with pytest.raises(ValueError, match="positional/insert"):
            record.save(force_insert=True, update_fields=["revision"])

    def test_update_fields_must_name_concrete_non_key_fields(self):
        record = FixtureRevisionedRecord.objects.create(label="first")

        record.revision = 2
        with pytest.raises(ValueError, match="concrete non-key fields"):
            record.save(update_fields=["id", "revision"])


class TestAppendOnlyManager:
    def test_insert_through_the_manager_succeeds(self):
        record = FixtureAppendOnlyRecord.objects.create(label="event-one")

        assert FixtureAppendOnlyRecord.objects.get(pk=record.pk).label == "event-one"

    def test_queryset_update_is_rejected(self):
        record = FixtureAppendOnlyRecord.objects.create(label="event-one")

        with pytest.raises(AppendOnlyViolation):
            FixtureAppendOnlyRecord.objects.filter(pk=record.pk).update(label="rewritten")

        assert FixtureAppendOnlyRecord.objects.get(pk=record.pk).label == "event-one"

    def test_instance_save_of_an_existing_row_is_not_intercepted_by_the_manager_alone(self):
        """Documents a real boundary of the base class, matching the donor.

        ``AppendOnlyQuerySet`` guards the manager-level API: ``.filter().update()``,
        ``.filter().delete()``, ``.bulk_create()`` and ``.bulk_update()``. A plain
        ``instance.save()`` on an existing row goes through Django's low-level
        single-row UPDATE path and never reaches the queryset, so it is not
        blocked by this base alone. In the donor, DTC's own ``AuditEvent`` closes
        this gap with its own ``save()`` override that forces every non-adding
        save to raise; that override is model-specific policy and is not part of
        the two classes this issue moves (see the kernel README).
        """

        record = FixtureAppendOnlyRecord.objects.create(label="event-one")

        record.label = "rewritten"
        record.save()

        assert FixtureAppendOnlyRecord.objects.get(pk=record.pk).label == "rewritten"

    def test_queryset_delete_is_rejected(self):
        record = FixtureAppendOnlyRecord.objects.create(label="event-one")

        with pytest.raises(AppendOnlyViolation):
            FixtureAppendOnlyRecord.objects.filter(pk=record.pk).delete()

        assert FixtureAppendOnlyRecord.objects.filter(pk=record.pk).exists()

    def test_instance_delete_is_not_intercepted_by_the_manager_alone(self):
        """The same gap as instance ``save()``, for the same reason.

        A single-row ``instance.delete()`` with no dependents uses Django's fast
        delete path and never reaches ``AppendOnlyQuerySet.delete()``. DTC's
        ``AuditEvent`` closes this with its own ``delete()`` override, which
        stays with that model rather than moving here.
        """

        record = FixtureAppendOnlyRecord.objects.create(label="event-one")

        record.delete()

        assert not FixtureAppendOnlyRecord.objects.filter(pk=record.pk).exists()

    def test_bulk_create_is_rejected(self):
        with pytest.raises(AppendOnlyViolation):
            FixtureAppendOnlyRecord.objects.bulk_create([FixtureAppendOnlyRecord(label="bypass")])

        assert not FixtureAppendOnlyRecord.objects.filter(label="bypass").exists()

    def test_bulk_update_is_rejected(self):
        record = FixtureAppendOnlyRecord.objects.create(label="event-one")
        record.label = "rewritten"

        with pytest.raises(AppendOnlyViolation):
            FixtureAppendOnlyRecord.objects.bulk_update([record], ["label"])

        assert FixtureAppendOnlyRecord.objects.get(pk=record.pk).label == "event-one"


def test_revisioned_model_is_abstract_and_defines_no_table():
    assert RevisionedModel._meta.abstract is True


def test_revision_field_is_a_positive_big_integer_defaulting_to_one():
    field = FixtureRevisionedRecord._meta.get_field("revision")

    assert isinstance(field, models.PositiveBigIntegerField)
    assert field.default == 1
