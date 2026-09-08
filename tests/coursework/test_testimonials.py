"""Donor-parity tests for testimonial placement, reads and portrait keys.

Mirrors `dtc-website/courses/tests/test_testimonials.py` (23 tests) against the
package surface: `community_base.coursework.models.Testimonial` and the
management service `community_base.coursework.testimonials`. Donor template and
view-level assertions are adapted to service-level assertions; the donor's
reviewed-set import, static-storage portrait resolution and Django admin
registration stay site-side and are recorded as not ported in
`docs/plan/evidence/c5.2e-studio-donors.md`.
"""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from community_base.coursework.models import Testimonial as MemberQuote
from community_base.coursework.models import (
    TestimonialPlacement as QuotePlacement,
)
from community_base.coursework.testimonials import (
    publish_testimonial,
    published_testimonials,
    reorder_testimonials,
    unpublish_testimonial,
)
from tests.curriculum.test_models import make_course

pytestmark = pytest.mark.django_db

HOMEPAGE = QuotePlacement.HOMEPAGE
COURSE = QuotePlacement.COURSE


def make_quote(**values):
    values.setdefault("placement", HOMEPAGE)
    values.setdefault("name", "Someone")
    values.setdefault("attribution", "Role · City")
    values.setdefault("quote", "A quote.")
    return MemberQuote.objects.create(**values)


def test_homepage_testimonial_cannot_name_a_course():
    course = make_course(slug="constraint-family", title="Constraint Family")

    with pytest.raises(IntegrityError), transaction.atomic():
        make_quote(placement=HOMEPAGE, course=course)


def test_course_testimonial_must_name_a_course():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_quote(placement=COURSE, course=None)


def test_an_unknown_placement_is_refused_outright():
    with pytest.raises(IntegrityError), transaction.atomic():
        make_quote(placement="somewhere-else", course=None)


def test_homepage_scope_without_course_is_accepted():
    homepage = make_quote(placement=HOMEPAGE, course=None)

    assert homepage.course is None


def test_course_scope_names_its_course():
    course = make_course(slug="constraint-family", title="Constraint Family")

    course_scoped = make_quote(placement=COURSE, course=course)

    assert course_scoped.course == course
    assert course_scoped == course.course_testimonials.get()


@pytest.mark.parametrize(
    "placement,with_course",
    [(HOMEPAGE, True), (COURSE, False)],
)
def test_clean_reports_the_stored_constraint_as_a_field_error(placement, with_course):
    course = make_course(slug="clean-family", title="Clean Family") if with_course else None

    testimonial = MemberQuote(placement=placement, course=course)

    with pytest.raises(ValidationError) as raised:
        testimonial.clean()
    assert "course" in raised.value.message_dict


def test_only_published_homepage_rows_are_returned_in_editor_order():
    course = make_course(slug="read-family", title="Read Family")
    make_quote(name="Second", quote="Second quote.", position=2, published=True)
    make_quote(name="First", quote="First quote.", position=1, published=True)
    make_quote(name="Unpublished", quote="Not live yet.", position=0, published=False)
    make_quote(
        placement=COURSE,
        course=course,
        name="Course scoped",
        quote="Belongs to a course page.",
        position=0,
        published=True,
    )

    stories = published_testimonials(HOMEPAGE)

    assert [story.name for story in stories] == ["First", "Second"]


def test_the_read_is_one_query(django_assert_num_queries):
    make_quote(name="Only", quote="Only quote.", published=True)

    with django_assert_num_queries(1):
        assert len(published_testimonials(HOMEPAGE)) == 1


def test_an_empty_table_yields_nothing_rather_than_raising():
    assert published_testimonials(HOMEPAGE) == []


def test_course_scoped_read_returns_only_that_courses_rows_in_editor_order():
    first = make_course(slug="read-family", title="Read Family")
    second = make_course(slug="other-family", title="Other Family")
    make_quote(placement=COURSE, course=first, name="Ours", position=1, published=True)
    make_quote(placement=COURSE, course=first, name="Ours first", position=0, published=True)
    make_quote(placement=COURSE, course=second, name="Theirs", position=0, published=True)
    make_quote(name="Homepage", quote="Homepage quote.", published=True)

    stories = published_testimonials(COURSE, course=first)

    assert [story.name for story in stories] == ["Ours first", "Ours"]


def test_rows_at_the_same_position_fall_back_to_id_order():
    older = make_quote(name="Older", quote="q", position=0, published=True)
    newer = make_quote(name="Newer", quote="q", position=0, published=True)

    assert published_testimonials(HOMEPAGE) == [older, newer]


@pytest.mark.parametrize(
    "key",
    [
        "/etc/passwd",
        "../secrets/key.jpg",
        "https://evil.invalid/pixel.gif",
        "//evil.invalid/pixel.gif",
        "testimonials\\example.jpg",
        "data:image/gif;base64,AAAA",
    ],
)
def test_a_key_that_escapes_its_prefix_is_refused_by_validation(key):
    story = MemberQuote(
        placement=HOMEPAGE, name="Someone", quote="A quote.", portrait_asset_key=key
    )

    with pytest.raises(ValidationError):
        story.full_clean(exclude=("course",))


def test_an_ordinary_relative_key_validates():
    story = MemberQuote(
        placement=HOMEPAGE,
        name="Someone",
        quote="A quote.",
        portrait_asset_key="testimonials/example.jpg",
    )

    story.full_clean(exclude=("course",))


def test_an_empty_key_is_valid_data():
    story = MemberQuote(placement=HOMEPAGE, name="Someone", quote="A quote.", portrait_asset_key="")

    story.full_clean(exclude=("course",))
    assert story.portrait_asset_key == ""


def test_reorder_assigns_consecutive_positions_within_one_placement():
    first = make_quote(name="A", position=5, published=True)
    second = make_quote(name="B", position=9, published=True)

    reorder_testimonials(HOMEPAGE, [second.id, first.id])

    first.refresh_from_db()
    second.refresh_from_db()
    assert [second.position, first.position] == [0, 1]
    assert list(MemberQuote.objects.filter(placement=HOMEPAGE).order_by("position")) == [
        second,
        first,
    ]


def test_unpublish_keeps_the_row_out_of_the_read_but_keeps_its_position():
    story = make_quote(name="A", position=3, published=True)

    publish_testimonial(story)
    assert published_testimonials(HOMEPAGE) == [story]

    unpublish_testimonial(story)
    story.refresh_from_db()
    assert published_testimonials(HOMEPAGE) == []
    assert story.position == 3
