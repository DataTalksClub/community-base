"""Apply a parsed curriculum graph to ``cb_curriculum`` rows.

The importer is source-of-truth driven: rows carrying this repository's
provenance are updated, created, or removed to match the graph. Rows without
provenance (Studio-managed) are never touched. A whole course that disappears
from its repository is soft-deleted to draft.

Checkouts that are not git working trees (fixture imports) carry no commit
sha; the importer derives a stable placeholder from the parser version and
graph content so provenance stays complete and re-imports stay idempotent.
"""

from __future__ import annotations

import hashlib
import re

from django.db import transaction
from django.utils import timezone

from community_base.curriculum.models import (
    Cohort,
    Course,
    CourseInstructor,
    CurriculumImportRun,
    Module,
    Unit,
)
from community_base.curriculum.source import InstructorGraph, ParsedCurriculum
from community_base.events.models import Host

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_UNCHANGED = "unchanged"
_NO_COMMIT = ""


def file_checksum(checkout, path: str | None) -> str:
    """Return the sha256 of a checkout file, or empty when there is no file."""

    if not path:
        return ""
    try:
        payload = checkout.read_bytes(path)
    except Exception:
        return ""
    return hashlib.sha256(payload).hexdigest()


def _stable_commit(parsed: ParsedCurriculum) -> str:
    payload = f"{parsed.parser_version}:{_manifest_checksum(parsed)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def apply_curriculum_graph(parsed: ParsedCurriculum, source, checkout) -> tuple[Course, dict]:
    """Apply the graph inside one transaction and record an import run.

    The run identity is (source, commit, parser version); re-importing an
    unchanged repository replays and updates the same run row, as the donor
    importer does.
    """

    owner, _, name = source.repo_name.rpartition("/")
    commit = parsed.commit_sha or _stable_commit(parsed)
    with transaction.atomic():
        run = CurriculumImportRun.objects.filter(
            source_uuid=source.pk,
            commit_sha=commit,
            parser_version=parsed.parser_version,
        ).first()
        if run is None:
            run = CurriculumImportRun(
                source_uuid=source.pk,
                source_stable_id=parsed.course.slug,
                repository_owner=owner or source.repo_name,
                repository_name=name or source.repo_name,
                repository_branch="",
                commit_sha=commit,
                schema_version=parsed.schema_version,
                parser_version=parsed.parser_version,
            )
        run.state = CurriculumImportRun.State.APPLYING
        run.started_at = timezone.now()
        run.finished_at = None
        run.counts = {}
        run.full_clean(exclude=["repository_branch"])
        run.save()

        try:
            course, counts = _apply(parsed, source, checkout, commit)
        except Exception:
            run.state = CurriculumImportRun.State.FAILED
            run.finished_at = timezone.now()
            run.save(update_fields=["state", "finished_at", "updated_at"])
            raise
        run.state = CurriculumImportRun.State.SUCCEEDED
        run.counts = counts
        run.manifest_checksum = _manifest_checksum(parsed)
        run.finished_at = timezone.now()
        run.save(
            update_fields=["state", "counts", "manifest_checksum", "finished_at", "updated_at"]
        )
        return course, counts


def _manifest_checksum(parsed) -> str:
    canonical = repr(sorted(_canonical(_graph_summary(parsed.course)).items()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _graph_summary(graph):
    def convert(value):
        if hasattr(value, "__dataclass_fields__"):
            return _graph_summary(value)
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        return value

    summary = {}
    for item in dataclass_fields_safe(graph):
        summary[item] = convert(getattr(graph, item))
    return summary


def dataclass_fields_safe(instance):
    return list(instance.__dataclass_fields__)


def _canonical(value):
    if isinstance(value, (tuple, set, list)):
        return sorted((_canonical(item) for item in value), key=repr)
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    return value


def _apply(parsed, source, checkout, commit) -> tuple[Course, dict]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0}
    graph = parsed.course

    course = _course(graph)
    action = _write(course, _course_values(graph, commit, checkout))
    counts[action] += 1
    _sync_instructors(course, graph)

    seen_cohort_ids = set()
    for cohort_graph in graph.cohorts:
        cohort = _cohort(course, cohort_graph)
        seen_cohort_ids.add(cohort_graph.content_id)
        counts[_write(cohort, _cohort_values(cohort_graph, commit, checkout))] += 1
        seen_module_ids = set()
        for position, module_graph in enumerate(cohort_graph.modules):
            module = _module(cohort, module_graph, position)
            seen_module_ids.add(module_graph.content_id)
            counts[_write(module, _module_values(module_graph, position, commit, checkout))] += 1
            seen_unit_ids = set()
            for unit_graph in module_graph.units:
                unit = _unit(module, unit_graph)
                seen_unit_ids.add(unit_graph.content_id)
                counts[_write(unit, _unit_values(unit_graph, commit, checkout))] += 1
            counts["deleted"] += _delete_stale(
                Unit.objects.filter(module=module).exclude(source_content_id__isnull=True),
                seen_unit_ids,
            )
        counts["deleted"] += _delete_stale(
            Module.objects.filter(cohort=cohort).exclude(source_content_id__isnull=True),
            seen_module_ids,
        )
    counts["deleted"] += _delete_stale(
        Cohort.objects.filter(course=course).exclude(source_content_id__isnull=True),
        seen_cohort_ids,
    )
    return course, counts


def _course(graph) -> Course:
    course = None
    if graph.content_id:
        course = Course.objects.filter(source_content_id=graph.content_id).first()
    if course is None:
        course = Course.objects.filter(slug=graph.slug).first()
    if course is None:
        course = Course(slug=graph.slug)
    course.source_content_id = graph.content_id
    return course


def _cohort(course: Course, graph) -> Cohort:
    cohort = None
    if graph.content_id:
        cohort = Cohort.objects.filter(course=course, source_content_id=graph.content_id).first()
    if cohort is None:
        cohort = Cohort.objects.filter(course=course, slug=graph.slug).first()
    if cohort is None:
        cohort = Cohort(course=course, slug=graph.slug)
    cohort.source_content_id = graph.content_id
    return cohort


def _module(cohort: Cohort, graph, position) -> Module:
    module = None
    if graph.content_id:
        module = Module.objects.filter(cohort=cohort, source_content_id=graph.content_id).first()
    if module is None:
        module = Module.objects.filter(cohort=cohort, slug=graph.slug).first()
    if module is None:
        module = Module(cohort=cohort, slug=graph.slug)
    module.source_content_id = graph.content_id
    return module


def _unit(module: Module, graph) -> Unit:
    unit = None
    if graph.content_id:
        unit = Unit.objects.filter(module=module, source_content_id=graph.content_id).first()
    if unit is None:
        unit = Unit.objects.filter(module=module, slug=graph.slug).first()
    if unit is None:
        unit = Unit(module=module, slug=graph.slug)
    unit.source_content_id = graph.content_id
    return unit


def _course_values(graph, commit, checkout) -> dict:
    return {
        "title": graph.title,
        "description": graph.description,
        "cover_image_url": graph.cover_image_url,
        "required_level": graph.required_level,
        "default_unit_required_level": graph.default_unit_required_level,
        "status": graph.status,
        "discussion_url": graph.discussion_url,
        "tags": list(graph.tags),
        "testimonials": list(graph.testimonials),
        "github_repo_url": graph.github_repo_url,
        "docs_url": graph.docs_url,
        "faq_url": graph.faq_url,
        "hashtag": graph.hashtag,
        "visible": graph.visible,
        **_prov(graph.source_path, commit, file_checksum(checkout, graph.source_path)),
    }


def _cohort_values(graph, commit, checkout) -> dict:
    return {
        "title": graph.title,
        "mode": graph.mode,
        "curriculum_format": graph.curriculum_format,
        "start_date": graph.start_date,
        "end_date": graph.end_date,
        "registration_url": graph.registration_url,
        "hashtag": graph.hashtag,
        "visible": graph.visible,
        **_prov(graph.source_path, commit, file_checksum(checkout, graph.source_path)),
    }


def _module_values(graph, position, commit, checkout) -> dict:
    sort_order = graph.sort_order or position
    return {
        "title": graph.title,
        "sort_order": sort_order,
        "overview": graph.overview,
        **_prov(graph.source_path, commit, file_checksum(checkout, graph.source_path)),
    }


def _unit_values(graph, commit, checkout) -> dict:
    return {
        "title": graph.title,
        "sort_order": graph.sort_order,
        "video_url": graph.video_url,
        "body": graph.body,
        "homework": graph.homework,
        "timestamps": list(graph.timestamps),
        "is_preview": graph.is_preview,
        "required_level": graph.required_level,
        "content_hash": _body_hash(graph),
        **_prov(graph.source_path, commit, file_checksum(checkout, graph.source_path)),
    }


def _prov(source_path, commit, checksum) -> dict:
    """All-or-nothing provenance, as the table constraint requires."""

    if not (source_path and commit and checksum):
        return {"source_path": None, "source_commit_sha": None, "source_checksum": None}
    return {
        "source_path": source_path,
        "source_commit_sha": commit,
        "source_checksum": checksum,
    }


def _body_hash(graph) -> str:
    payload = graph.body or graph.homework or ""
    return hashlib.md5(payload.encode("utf-8")).hexdigest() if payload else ""


def _write(instance, values) -> str:
    """Write ``values`` when they differ; return created/updated/unchanged."""

    was_new = instance.pk is None
    content_keys = [key for key in values if key not in _PROVENANCE_KEYS]
    if not was_new:
        changed = any(
            _canonical(getattr(instance, key)) != _canonical(values[key]) for key in content_keys
        )
        if not changed:
            for key in _PROVENANCE_KEYS:
                setattr(instance, key, values[key])
            fields = [*_PROVENANCE_KEYS, "source_content_id"]
            instance.save(update_fields=fields)
            return ACTION_UNCHANGED
    for key, value in values.items():
        setattr(instance, key, value)
    instance.save()
    return ACTION_CREATED if was_new else ACTION_UPDATED


_PROVENANCE_KEYS = ("source_path", "source_commit_sha", "source_checksum")


def _delete_stale(queryset, seen_ids: set) -> int:
    seen = {str(value) for value in seen_ids if value is not None}
    stale = [
        row
        for row in queryset
        if row.source_content_id is None or str(row.source_content_id) not in seen
    ]
    for row in stale:
        row.delete()
    return len(stale)


def _sync_instructors(course: Course, graph) -> None:
    for position, entry in enumerate(graph.instructors):
        if not isinstance(entry, InstructorGraph):
            continue
        host = None
        if entry.slug:
            host = Host.objects.filter(slug=entry.slug, kind="instructor").first()
        if host is None:
            host = Host.objects.filter(name=entry.name, kind="instructor").first()
        if host is None:
            host = Host.objects.create(
                name=entry.name,
                slug=entry.slug or _host_slug(entry.name),
                kind="instructor",
                bio=entry.bio,
            )
        elif entry.bio and host.bio != entry.bio:
            host.bio = entry.bio
            host.save(update_fields=["bio", "bio_html", "updated_at"])
        CourseInstructor.objects.update_or_create(
            course=course, host=host, defaults={"position": position}
        )


def _host_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "instructor"
