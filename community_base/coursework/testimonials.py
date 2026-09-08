"""Testimonial management surface.

The homepage/course testimonials are Studio-managed rows; the donor's CSV
import of reviewed copy stays a site concern. The package owns the state
changes: publish, unpublish and reorder within one placement, plus the read
helpers both sites use.
"""

from django.db import transaction

from community_base.coursework.models import Testimonial, TestimonialPlacement


def published_testimonials(placement, course=None):
    """Published rows for a placement, display order; course-scoped for COURSE."""
    queryset = Testimonial.objects.filter(placement=placement, published=True)
    if placement == TestimonialPlacement.COURSE:
        queryset = queryset.filter(course=course)
    return list(queryset)


@transaction.atomic
def publish_testimonial(testimonial):
    testimonial.published = True
    testimonial.save(update_fields=["published"])
    return testimonial


@transaction.atomic
def unpublish_testimonial(testimonial):
    testimonial.published = False
    testimonial.save(update_fields=["published"])
    return testimonial


@transaction.atomic
def reorder_testimonials(placement, ordered_ids):
    """Assign consecutive positions in the given order within one placement."""
    testimonials = Testimonial.objects.filter(placement=placement, id__in=ordered_ids)
    by_id = {testimonial.id: testimonial for testimonial in testimonials}
    missing = set(ordered_ids) - set(by_id)
    if missing:
        raise ValueError(f"Unknown testimonial ids for {placement}: {sorted(missing)}")
    updated = []
    for position, testimonial_id in enumerate(ordered_ids):
        testimonial = by_id[testimonial_id]
        testimonial.position = position
        updated.append(testimonial)
    Testimonial.objects.bulk_update(updated, ["position"])
    return updated
