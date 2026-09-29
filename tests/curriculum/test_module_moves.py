"""Module identity survives valid moves through the shared graph importer."""

from dataclasses import replace

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError

from community_base.curriculum.models import CohortModule, CurriculumImportRun, Module, Unit
from community_base.curriculum.source import CurriculumParseError
from tests.curriculum.module_move_fixtures import (
    COHORT,
    TOPIC,
    apply_tree,
    identity,
    learner_rows,
    module,
    snapshot,
)

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("reverse", [False, True])
def test_unchanged_child_moves_between_retained_parents(tmp_path, reverse):
    before = (module("left", children=(TOPIC,)), module("right", sort_order=2))
    after = (module("left"), module("right", children=(TOPIC,), sort_order=2))
    if reverse:
        before, after = after, before
    course, _ = apply_tree(tmp_path, before)
    topic = course.modules.get(slug="topic")
    unit = topic.units.get()
    old_parent = topic.parent_id

    _, counts = apply_tree(tmp_path, after)

    topic.refresh_from_db()
    unit.refresh_from_db()
    assert topic.parent_id != old_parent
    assert topic.parent.children.get().pk == topic.pk
    assert unit.module_id == topic.pk
    assert Module.objects.count() == 3
    assert Unit.objects.count() == 1
    assert counts == {"created": 0, "updated": 1, "unchanged": 5, "deleted": 0}
    _, repeated = apply_tree(tmp_path, after)
    assert repeated == {"created": 0, "updated": 0, "unchanged": 6, "deleted": 0}


@pytest.mark.parametrize("reverse", [False, True])
def test_removing_old_parent_preserves_module_units_and_learner_rows(tmp_path, reverse):
    before = (module("old", children=(TOPIC,)), module("destination", sort_order=2))
    if reverse:
        before = tuple(reversed(before))
    course, _ = apply_tree(tmp_path, before)
    topic = course.modules.get(slug="topic")
    unit = topic.units.get()
    rows = learner_rows(topic)
    stored = snapshot(rows)

    _, counts = apply_tree(tmp_path, (module("destination", children=(TOPIC,), sort_order=2),))

    assert Module.objects.filter(pk=topic.pk).exists()
    topic.refresh_from_db()
    unit.refresh_from_db()
    assert topic.parent.slug == "destination"
    assert unit.module_id == topic.pk
    assert snapshot(rows) == stored
    assert not course.modules.filter(slug="old").exists()
    assert counts["deleted"] == 1
    assert counts["updated"] == 1


@pytest.mark.parametrize("demote", [False, True])
def test_leaf_promotion_and_demotion_keep_identity(tmp_path, demote):
    nested = (module("parent", children=(TOPIC,)),)
    top_level = (module("parent"), TOPIC)
    before, after = nested, top_level
    expected_parent = None
    if demote:
        before, after = top_level, nested
        expected_parent = "parent"
    course, _ = apply_tree(tmp_path, before)
    topic = course.modules.get(slug="topic")
    unit = topic.units.get()

    _, counts = apply_tree(tmp_path, after)

    topic.refresh_from_db()
    assert (
        topic.parent_id
        == course.modules.filter(slug=expected_parent).values_list("pk", flat=True).first()
    )
    assert topic.units.get().pk == unit.pk
    for row in course.modules.all():
        row.full_clean()
    assert counts["updated"] == 1
    assert apply_tree(tmp_path, after)[1]["updated"] == 0


@pytest.mark.parametrize("replacement_id", [None, identity("replacement")])
def test_same_parent_slug_fallback_keeps_module_and_unit(tmp_path, replacement_id):
    course, _ = apply_tree(tmp_path, (module("parent", children=(TOPIC,)),))
    topic = course.modules.get(slug="topic")
    unit = topic.units.get()
    changed = replace(TOPIC, content_id=replacement_id)

    _, counts = apply_tree(tmp_path, (module("parent", children=(changed,)),))

    topic.refresh_from_db()
    assert str(topic.source_content_id or "") == str(replacement_id or "")
    assert topic.units.get().pk == unit.pk
    assert counts == {"created": 0, "updated": 0, "unchanged": 5, "deleted": 0}


def test_identity_lookup_preserves_stored_slug_when_module_moves(tmp_path):
    course, _ = apply_tree(tmp_path, (module("parent", children=(TOPIC,)),))
    topic = course.modules.get(slug="topic")
    moved = replace(TOPIC, slug="renamed-in-source")

    apply_tree(tmp_path, (module("destination", children=(moved,)),))

    topic.refresh_from_db()
    assert topic.slug == "topic"
    assert topic.parent.slug == "destination"
    assert topic.source_path == "destination/renamed-in-source/module.yaml"


def test_reused_module_uuid_in_an_independent_course_stays_separate(tmp_path):
    before = (module("parent", children=(TOPIC,)),)
    first, _ = apply_tree(tmp_path, before)
    second, _ = apply_tree(tmp_path, before, course_slug="second")
    first_topic = first.modules.get(slug="topic")
    second_topic = second.modules.get(slug="topic")
    second_rows = snapshot((second_topic, second_topic.units.get()))

    apply_tree(tmp_path, (module("destination", children=(TOPIC,)),))

    first_topic.refresh_from_db()
    assert first_topic.parent.slug == "destination"
    assert first_topic.pk != second_topic.pk
    assert snapshot((second_topic, second_topic.units.get())) == second_rows


def test_demotion_synchronizes_existing_top_level_placements(tmp_path):
    placed = replace(COHORT, module_refs=(TOPIC.content_id,))
    course, _ = apply_tree(tmp_path, (TOPIC, module("parent")), cohort=placed)
    topic = course.modules.get(slug="topic")
    placement = CohortModule.objects.get(module=topic)
    apply_tree(tmp_path, (module("parent", children=(TOPIC,)),))

    assert not CohortModule.objects.exists()
    moved = replace(COHORT, module_refs=(identity("parent"),))
    apply_tree(tmp_path, (module("parent", children=(TOPIC,)),), cohort=moved)

    assert not CohortModule.objects.filter(pk=placement.pk).exists()
    placement = CohortModule.objects.get()
    assert placement.module.slug == "parent"
    placement.full_clean()
    topic.refresh_from_db()
    with pytest.raises(ValidationError, match="top-level"):
        CohortModule(cohort=placement.cohort, module=topic, sort_order=1).full_clean()
    apply_tree(tmp_path, (module("parent", children=(TOPIC,)),))
    assert not CohortModule.objects.exists()
    assert list(course.cohorts.get().effective_modules()) == [placement.module]


def test_child_placement_reference_rolls_back_the_move(tmp_path):
    placed = replace(COHORT, module_refs=(TOPIC.content_id,))
    course, _ = apply_tree(tmp_path, (TOPIC, module("parent")), cohort=placed)
    topic = course.modules.get(slug="topic")
    stored = snapshot((topic, CohortModule.objects.get()))

    with pytest.raises(CurriculumParseError, match="unknown top-level module"):
        apply_tree(tmp_path, (module("parent", children=(TOPIC,)),), cohort=placed)

    assert snapshot((topic, CohortModule.objects.get())) == stored


def test_destination_slug_collision_rolls_back_every_write(tmp_path):
    before = (module("old", children=(TOPIC,)), module("destination", sort_order=2))
    course, _ = apply_tree(tmp_path, before)
    topic = course.modules.get(slug="topic")
    destination = course.modules.get(slug="destination")
    collision = Module.objects.create(
        course=course, parent=destination, slug="topic", title="Local"
    )
    rows = (course, topic, destination, collision, topic.units.get(), *learner_rows(topic))
    stored = snapshot(rows)
    runs = list(CurriculumImportRun.objects.values())

    with pytest.raises(DatabaseError) as error:
        apply_tree(tmp_path, (module("destination", children=(TOPIC,)),), title="Changed")

    assert isinstance(error.value.__cause__ or error.value, IntegrityError)
    assert snapshot(rows) == stored
    assert list(CurriculumImportRun.objects.values()) == runs
