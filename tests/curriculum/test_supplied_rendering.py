"""A unit whose HTML the sync parser rendered (C7.8, mirroring C7.4 for pages)."""

import pytest

from community_base.curriculum.models import (
    BODY_HTML_MARKDOWN,
    BODY_HTML_SITE,
    Course,
    Module,
    Unit,
)

pytestmark = pytest.mark.django_db

SUPPLIED_HTML = '<div class="synced"><h2 id="intro">Intro</h2><p>Body.</p></div>'


def make_unit(**values):
    course = Course.objects.create(slug="course", title="Course")
    module = Module.objects.create(course=course, slug="module", title="Module")
    values.setdefault("slug", "welcome")
    values.setdefault("title", "Welcome")
    return Unit.objects.create(module=module, **values)


def test_a_unit_renders_its_markdown_by_default():
    unit = make_unit(body="**bold** text")

    assert unit.body_html_source == BODY_HTML_MARKDOWN
    assert "<strong>bold</strong>" in unit.body_html


def test_supplied_html_replaces_the_markdown_rendering():
    unit = make_unit(body="**bold** text")
    unit.set_rendered_html(SUPPLIED_HTML)
    unit.save()
    unit.refresh_from_db()

    assert unit.body_html_source == BODY_HTML_SITE
    assert unit.body_html == SUPPLIED_HTML
    assert "<strong>bold</strong>" not in unit.body_html


def test_supplied_html_survives_a_further_save_untouched():
    unit = make_unit(body="**bold** text")
    unit.set_rendered_html(SUPPLIED_HTML)
    unit.save()

    stored = Unit.objects.get(pk=unit.pk)
    stored.title = "Welcome, renamed"
    stored.save()
    stored.refresh_from_db()

    assert stored.body_html == SUPPLIED_HTML


def test_supplied_html_is_not_trusted():
    unit = make_unit()
    unit.set_rendered_html(
        '<p onclick="steal()">Text</p><script>alert(1)</script>'
        '<a href="javascript:alert(1)">link</a>'
    )
    unit.save()
    unit.refresh_from_db()

    assert "<script>" not in unit.body_html
    assert "onclick" not in unit.body_html
    assert "javascript:" not in unit.body_html
    assert "Text" in unit.body_html


def test_a_unit_can_be_handed_back_to_the_app_renderer():
    unit = make_unit(body="**bold** text")
    unit.set_rendered_html(SUPPLIED_HTML)
    unit.save()

    unit.body_html_source = BODY_HTML_MARKDOWN
    unit.save()
    unit.refresh_from_db()

    assert "<strong>bold</strong>" in unit.body_html


def test_supplied_html_does_not_stop_the_homework_from_rendering():
    unit = make_unit(body="ignored", homework="Do the **task**.")
    unit.set_rendered_html(SUPPLIED_HTML)
    unit.save()
    unit.refresh_from_db()

    assert unit.body_html == SUPPLIED_HTML
    assert "<strong>task</strong>" in unit.homework_html
