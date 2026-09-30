"""Member API syllabus serialization over the shared curriculum projection."""

from community_base.api.public_urls import public_url
from community_base.curriculum.projection import CourseTree, get_syllabus


def _unit_payload(node):
    unit = node.item
    return {
        "id": unit.pk,
        "slug": unit.slug,
        "title": unit.title,
        "sort_order": unit.sort_order,
        "is_preview": unit.is_preview,
    }


def _module_payload(node, *, nested=False):
    module = node.item
    units, children = [], []
    for child in node.children:
        if child.is_module:
            children.append(_module_payload(child, nested=True))
        else:
            units.append(_unit_payload(child))
    data = {
        "id": module.pk,
        "slug": module.slug,
        "title": module.title,
        "sort_order": module.sort_order,
        "units": units,
    }
    if children:
        data["children"] = children
    if children or nested:
        data["siblings"] = [_sibling_reference(child) for child in node.children]
    return data


def _sibling_reference(node):
    """Ordered, shallow links; each full module/unit is serialized exactly once."""
    kind = "unit"
    if node.is_module:
        kind = "module"
    data = {
        "id": node.item.pk,
        "type": kind,
        "title": node.item.title,
        "public_url": public_url(node, is_public=True),
        "is_bonus": node.item.effective_is_bonus,
    }
    if node.is_module:
        data["syllabus_section"] = node.item.syllabus_section
    return data


def syllabus_payload(course):
    tree = CourseTree(course)
    result = []
    for cohort in get_syllabus(course, tree):
        projection = tree.project(cohort)
        result.append(
            {"cohort": cohort.slug, "modules": [_module_payload(node) for node in projection.roots]}
        )
    return result
