"""API serialization work stays linear at the supported module depth."""

from collections import Counter

import pytest

from community_base.curriculum import syllabus
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


def counted(original, calls):
    def record(node, **kwargs):
        calls.append(node.item.pk)
        return original(node, **kwargs)

    return record


@pytest.mark.parametrize("width", [1, 12])
def test_each_full_module_and_unit_payload_is_serialized_once(width, monkeypatch):
    course = make_course()
    make_cohort(course)
    modules, units = [], []
    for index in range(width):
        root = make_module(course, slug=f"root-{index}")
        child = make_module(course, parent=root, slug="child", source_sibling_position=1)
        modules.extend([root.pk, child.pk])
        units.append(make_unit(root, source_sibling_position=0).pk)
        units.append(make_unit(child).pk)
    module_calls, unit_calls = [], []
    monkeypatch.setattr(
        syllabus, "_module_payload", counted(syllabus._module_payload, module_calls)
    )
    monkeypatch.setattr(syllabus, "_unit_payload", counted(syllabus._unit_payload, unit_calls))
    payload = syllabus.syllabus_payload(course)[0]["modules"]
    assert Counter(module_calls) == Counter(modules)
    assert Counter(unit_calls) == Counter(units)
    for root in payload:
        assert "units" not in root["siblings"][1] and "children" not in root["siblings"][1]
        assert "siblings" not in root["siblings"][1]
        assert root["children"][0]["siblings"][0]["public_url"]
