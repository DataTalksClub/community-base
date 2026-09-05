from datetime import datetime

from django.template import Context, Template


def render(source, context=None):
    return Template("{% load studio_filters %}" + source).render(Context(context or {}))


def test_operator_dates_and_dict_lookup():
    value = datetime(2026, 9, 5, 14, 3, 2)

    result = render(
        "{{ value|operator_date }} {{ value|operator_datetime_seconds }} {{ data|dict_get:'key' }}",
        {"value": value, "data": {"key": "found"}},
    )

    assert result == "2026-09-05 2026-09-05 14:03:02 found"


def test_status_badge_and_list_action_render_components():
    result = render(
        "{% studio_status_badge 'published' %}{% studio_list_action '/items/' 'View' %}"
    )

    assert "Published" in result
    assert 'href="/items/"' in result
    assert "bg-green-500/20" in result


def test_list_class_supports_right_aligned_heading():
    assert "text-right" in render("{% studio_list_class 'th' 'right' %}")
