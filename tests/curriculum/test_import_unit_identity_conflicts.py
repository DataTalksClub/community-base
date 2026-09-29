"""Final-slot conflicts reject before writes; valid swaps remain atomic."""

from dataclasses import replace
from unittest.mock import patch
from uuid import UUID

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from community_base.curriculum import importing
from community_base.curriculum.models import Course, CurriculumImportRun, Module, Unit
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.test_import_unit_identity_fixtures import (
    apply_graph,
    identity,
    module_graph,
    parsed_graph,
    unit_graph,
)

pytestmark = pytest.mark.django_db


def snapshot():
    result = {}
    for model in (Course, Module, Unit, CurriculumImportRun):
        result[model.__name__] = list(model.objects.order_by("pk").values())
    return result


def assert_rejected_before_writes(graph, message):
    before = snapshot()
    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(CurriculumParseError, match=message):
            apply_graph(graph)
    writes = []
    for query in queries:
        if query["sql"].split()[0] in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(query["sql"])
    assert writes == []
    assert snapshot() == before


@pytest.mark.parametrize("representation", [str, UUID, lambda value: value.replace("-", "")])
def test_duplicate_incoming_identity_rejected_before_writes(representation):
    authored = unit_graph()
    apply_graph(parsed_graph([module_graph(2, [authored]), module_graph(3)]))
    duplicate = replace(authored, content_id=representation(authored.content_id))
    graph = parsed_graph([module_graph(2, [authored]), module_graph(3, [duplicate])])
    assert_rejected_before_writes(graph, "duplicate unit content_id")


def test_ambiguous_existing_identity_rejected_before_writes():
    authored = unit_graph()
    apply_graph(parsed_graph([module_graph(2, [authored]), module_graph(3)]))
    Unit.objects.create(
        module=Module.objects.get(slug="module-3"),
        slug="duplicate",
        title="Duplicate",
        source_content_id=authored.content_id,
    )
    assert_rejected_before_writes(
        parsed_graph([module_graph(2, [authored]), module_graph(3)]), "ambiguous unit content_id"
    )


def test_unmanaged_occupied_destination_rejected_before_writes():
    authored = unit_graph()
    apply_graph(parsed_graph([module_graph(2, [authored]), module_graph(3)]))
    Unit.objects.create(module=Module.objects.get(slug="module-3"), slug="lesson", title="Manual")
    assert_rejected_before_writes(
        parsed_graph([module_graph(2), module_graph(3, [authored])]), "occupied unit destination"
    )


def test_two_final_stored_slugs_cannot_claim_same_destination():
    first, second = unit_graph(10), unit_graph(11)
    apply_graph(parsed_graph([module_graph(2, [first]), module_graph(3, [second])]))
    graph = parsed_graph(
        [module_graph(2), module_graph(3, [first, replace(second, slug="new-slug")])]
    )
    assert_rejected_before_writes(graph, "duplicate unit destination")


@pytest.mark.parametrize("size", [2, 3])
def test_same_slug_cycle_retains_each_identity(size):
    authored = [unit_graph(10 + index) for index in range(size)]
    modules = []
    for index, unit in enumerate(authored):
        modules.append(module_graph(2 + index, [unit]))
    apply_graph(parsed_graph(modules))
    before = dict(Unit.objects.values_list("source_content_id", "pk"))
    moved = []
    for index in range(size):
        moved.append(module_graph(2 + index, [authored[(index + 1) % size]]))
    _course, counts = apply_graph(parsed_graph(moved))
    assert counts["updated"] == size
    for index, module in enumerate(moved):
        unit = Unit.objects.get(pk=before[UUID(module.units[0].content_id)])
        assert unit.module.slug == f"module-{index + 2}"
        assert unit.slug == "lesson"
    assert apply_graph(parsed_graph(moved))[1]["updated"] == 0


def test_move_can_replace_truly_stale_managed_destination():
    moving, stale = unit_graph(10), unit_graph(11)
    apply_graph(parsed_graph([module_graph(2, [moving]), module_graph(3, [stale])]))
    original = Unit.objects.get(source_content_id=moving.content_id)
    stale_pk = Unit.objects.get(source_content_id=stale.content_id).pk
    _course, counts = apply_graph(parsed_graph([module_graph(2), module_graph(3, [moving])]))
    original.refresh_from_db()
    assert original.module.slug == "module-3"
    assert original.slug == "lesson"
    assert not Unit.objects.filter(pk=stale_pk).exists()
    assert counts == {"created": 0, "updated": 1, "unchanged": 3, "deleted": 1}


@pytest.mark.parametrize("new_id", [None, identity(12)])
def test_new_unit_in_old_slot_does_not_steal_reserved_moving_identity(new_id):
    moving = unit_graph(10)
    apply_graph(parsed_graph([module_graph(2, [moving]), module_graph(3)]))
    original = Unit.objects.get()
    replacement = unit_graph(content_id=new_id, source_path="")
    graph = parsed_graph([module_graph(2, [replacement]), module_graph(3, [moving])])
    apply_graph(graph)
    original.refresh_from_db()
    assert original.module.slug == "module-3"
    new_unit = Unit.objects.get(module__slug="module-2")
    assert new_unit.pk != original.pk
    assert str(new_unit.source_content_id) == str(new_id)


def test_failure_after_first_move_rolls_back_rows_and_temporary_slugs():
    first, second = unit_graph(10), unit_graph(11)
    apply_graph(parsed_graph([module_graph(2, [first]), module_graph(3, [second])]))
    before = snapshot()
    calls = []
    writer = importing.write_values

    def fail_second_unit(instance, values):
        if isinstance(instance, Unit):
            calls.append(instance.pk)
            if len(calls) == 2:
                raise RuntimeError("injected after first unit write")
        return writer(instance, values)

    graph = parsed_graph([module_graph(2, [second]), module_graph(3, [first])])
    with patch.object(importing, "write_values", side_effect=fail_second_unit):
        with pytest.raises(RuntimeError, match="injected after first unit write"):
            apply_graph(graph)
    assert len(calls) == 2
    assert snapshot() == before


def test_module_aliases_cannot_claim_same_stored_unit_destination():
    apply_graph(parsed_graph([module_graph(2)]))
    first = module_graph(2, [unit_graph(10)], slug="renamed-module")
    second = module_graph(3, [unit_graph(11)], slug="module-2")
    assert_rejected_before_writes(parsed_graph([first, second]), "duplicate unit destination")
