"""Persist course instructors using the host model installed by the consumer."""

import re

from community_base.curriculum.models import CourseInstructor
from community_base.curriculum.source import InstructorGraph


def sync_instructors(course, graph) -> None:
    if not graph.instructors:
        return
    host_model = CourseInstructor._meta.get_field("host").remote_field.model
    for position, entry in enumerate(graph.instructors):
        if not isinstance(entry, InstructorGraph):
            continue
        host = instructor_host(host_model, entry)
        CourseInstructor.objects.update_or_create(
            course=course, host=host, defaults={"position": position}
        )


def instructor_host(host_model, entry):
    host = None
    if entry.slug:
        host = host_model.objects.filter(slug=entry.slug, kind="instructor").first()
    if host is None:
        host = host_model.objects.filter(name=entry.name, kind="instructor").first()
    if host is None:
        return host_model.objects.create(
            name=entry.name,
            slug=entry.slug or host_slug(entry.name),
            kind="instructor",
            bio=entry.bio,
        )
    if entry.bio and host.bio != entry.bio:
        host.bio = entry.bio
        host.save(update_fields=["bio", "bio_html", "updated_at"])
    return host


def host_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "instructor"
