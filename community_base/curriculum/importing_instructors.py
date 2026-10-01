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
    kind = _instructor_kind(host_model)
    host = None
    if entry.slug:
        host = host_model.objects.filter(slug=entry.slug, **kind).first()
    if host is None:
        host = host_model.objects.filter(name=entry.name, **kind).first()
    if host is None:
        values = {
            "name": entry.name,
            "slug": entry.slug or host_slug(entry.name),
            "bio": entry.bio,
        }
        values.update(kind)
        return host_model.objects.create(**values)
    if entry.bio and host.bio != entry.bio:
        host.bio = entry.bio
        host.save(update_fields=["bio", "bio_html", "updated_at"])
    return host


def _instructor_kind(host_model):
    fields = {field.name for field in host_model._meta.concrete_fields}
    if "kind" in fields:
        return {"kind": "instructor"}
    return {}


def host_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "instructor"
