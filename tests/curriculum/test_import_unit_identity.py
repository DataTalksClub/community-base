"""Moving authored units preserves their identity and learner-owned links."""

from dataclasses import replace

import pytest

from community_base.curriculum.models import Module, Unit
from tests.curriculum.test_import_unit_identity_fixtures import (
    apply_graph,
    identity,
    learner_rows,
    module_graph,
    parsed_graph,
    unit_graph,
)
from tests.curriculum.utils import make_source

pytestmark = pytest.mark.django_db


def persisted_values(row):
    return {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}


@pytest.mark.parametrize("origin,destination", [(2, 3), (3, 2)])
@pytest.mark.parametrize("path_changes", [False, True])
def test_move_preserves_pk_and_counts_update_once(origin, destination, path_changes):
    authored = unit_graph()
    modules = {2: module_graph(2), 3: module_graph(3)}
    modules[origin] = replace(modules[origin], units=(authored,))
    apply_graph(parsed_graph(modules.values()))
    original = Unit.objects.get()
    modules[origin] = replace(modules[origin], units=())
    moved = authored
    if path_changes:
        moved = replace(authored, source_path=f"{destination}/lesson.md")
    modules[destination] = replace(modules[destination], units=(moved,))
    graph = parsed_graph(modules.values())
    _course, counts = apply_graph(graph)
    original.refresh_from_db()
    assert original.module.source_content_id.hex == identity(destination).replace("-", "")
    assert original.source_path == moved.source_path
    assert counts == {"created": 0, "updated": 1, "unchanged": 3, "deleted": 0}
    assert apply_graph(graph)[1] == {"created": 0, "updated": 0, "unchanged": 4, "deleted": 0}
    assert list(Unit.objects.values_list("pk", flat=True)) == [original.pk]


def test_move_out_of_removed_module_preserves_learner_rows():
    authored = unit_graph()
    apply_graph(parsed_graph([module_graph(2, [authored]), module_graph(3)]))
    original = Unit.objects.get()
    rows = learner_rows(original)
    expected = [persisted_values(row) for row in rows]
    old_module_id = original.module_id
    apply_graph(parsed_graph([module_graph(3, [authored])]))
    original.refresh_from_db()
    assert not Module.objects.filter(pk=old_module_id).exists()
    assert original.module.source_content_id.hex == identity(3).replace("-", "")
    for row, before in zip(rows, expected, strict=True):
        row.refresh_from_db()
        if "module_id" in before:
            before["module_id"] = None
        assert persisted_values(row) == before
    assert rows[0].unit_id == rows[1].unit_id == original.pk


@pytest.mark.parametrize("new_identity", [None, identity(11)])
def test_unmatched_identity_retains_existing_module_slug_fallback(new_identity):
    authored = unit_graph()
    apply_graph(parsed_graph([module_graph(2, [authored])]))
    original = Unit.objects.get()
    replacement = replace(authored, content_id=new_identity, source_path="")
    apply_graph(parsed_graph([module_graph(2, [replacement])]))
    original.refresh_from_db()
    assert str(original.source_content_id) == str(new_identity)
    assert Unit.objects.count() == 1


def test_missing_identity_reuses_unmanaged_slug():
    authored = unit_graph(content_id=None, source_path="")
    graph = parsed_graph([module_graph(2, [authored])])
    apply_graph(graph)
    original = Unit.objects.get()
    assert apply_graph(graph)[1]["created"] == 0
    assert Unit.objects.get().pk == original.pk


def test_move_preserves_stored_slug():
    authored = unit_graph()
    apply_graph(parsed_graph([module_graph(2, [authored]), module_graph(3)]))
    original = Unit.objects.get()
    renamed = replace(authored, slug="renamed")
    apply_graph(parsed_graph([module_graph(2), module_graph(3, [renamed])]))
    original.refresh_from_db()
    assert original.slug == "lesson"
    assert original.module.slug == "module-3"


def test_independent_repository_unit_uuid_is_scoped_to_its_course():
    authored = unit_graph()
    graph = parsed_graph([module_graph(2, [authored]), module_graph(3)])
    first, _counts = apply_graph(graph)
    other_graph = replace(
        graph, course=replace(graph.course, content_id=identity(20), slug="other")
    )
    second, _counts = apply_graph(other_graph, make_source("other", "elsewhere/other"))
    other = Unit.objects.get(module__course=second)
    moved = parsed_graph([module_graph(2), module_graph(3, [authored])])
    apply_graph(moved)
    other.refresh_from_db()
    assert other.module.course_id == second.pk
    assert other.module.slug == "module-2"
    assert Unit.objects.get(module__course=first).module.slug == "module-3"


def test_true_stale_cleanup_retains_unmanaged_units():
    apply_graph(parsed_graph([module_graph(2, [unit_graph()])]))
    original = Unit.objects.get()
    unmanaged = Unit.objects.create(module=original.module, slug="manual", title="Manual")
    _course, counts = apply_graph(parsed_graph([module_graph(2)]))
    assert counts["deleted"] == 1
    assert list(Unit.objects.values_list("pk", flat=True)) == [unmanaged.pk]


def test_move_from_nested_leaf_into_new_top_level_module():
    authored = unit_graph()
    leaf = module_graph(3, [authored])
    parent = module_graph(2, children=(leaf,))
    apply_graph(parsed_graph([parent]))
    original = Unit.objects.get()
    apply_graph(parsed_graph([module_graph(4, [authored])]))
    original.refresh_from_db()
    assert original.module.slug == "module-4"
    assert original.module.parent_id is None
    assert Module.objects.count() == 1
    assert Unit.objects.count() == 1


def test_same_slug_units_in_distinct_leaf_modules_stay_independent():
    graph = parsed_graph([module_graph(2, [unit_graph(10)]), module_graph(3, [unit_graph(11)])])
    apply_graph(graph)
    before = dict(Unit.objects.values_list("source_content_id", "pk"))
    assert len(before) == 2
    assert apply_graph(graph)[1] == {"created": 0, "updated": 0, "unchanged": 5, "deleted": 0}
    assert dict(Unit.objects.values_list("source_content_id", "pk")) == before


def test_removed_module_counts_as_one_deletion_including_its_stale_units():
    graph = parsed_graph([module_graph(2, [unit_graph(10), unit_graph(11, slug="extra")])])
    apply_graph(graph)
    _course, counts = apply_graph(parsed_graph([]))
    assert counts == {"created": 0, "updated": 0, "unchanged": 1, "deleted": 1}
    assert not Module.objects.exists()
    assert not Unit.objects.exists()


def test_stale_units_in_retained_module_without_identity_are_deleted():
    module = module_graph(2, [unit_graph()], content_id=None, source_path="")
    apply_graph(parsed_graph([module]))
    original_module = Module.objects.get()
    _course, counts = apply_graph(parsed_graph([replace(module, units=())]))
    assert counts["deleted"] == 1
    assert Module.objects.get().pk == original_module.pk
    assert not Unit.objects.exists()
