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

from django.db import transaction
from django.utils import timezone

from community_base.curriculum.importing_instructors import sync_instructors as _sync_instructors
from community_base.curriculum.importing_units import UnitImport
from community_base.curriculum.importing_values import (
    cohort_values,
    course_values,
    file_checksum,
    module_values,
    provenance,
    unit_values,
)
from community_base.curriculum.models import (
    Cohort,
    CohortModule,
    Course,
    CurriculumImportRun,
    Module,
)
from community_base.curriculum.source import (
    CurriculumParseError,
    ParsedCurriculum,
    UnitGraph,
)

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_UNCHANGED = "unchanged"
_NO_COMMIT = ""
__all__ = ("apply_curriculum_graph", "delete_stale", "file_checksum", "provenance", "write_values")


def _stable_commit(parsed: ParsedCurriculum) -> str:
    payload = f"{parsed.parser_version}:{_manifest_checksum(parsed)}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def graph_commit(parsed: ParsedCurriculum) -> str:
    """The commit every row of this graph carries.

    A fixture checkout is not a git working tree and has no commit sha, so the
    placeholder derived from the graph keeps provenance complete and re-imports
    idempotent. Anything importing rows alongside this graph -- the coursework
    homework of issue C7.11 -- takes its commit from here, so one sync writes
    one commit.
    """

    return parsed.commit_sha or _stable_commit(parsed)


def apply_curriculum_graph(parsed: ParsedCurriculum, source, checkout) -> tuple[Course, dict]:
    """Apply the graph inside one transaction and record an import run.

    The run identity is (source, commit, parser version); re-importing an
    unchanged repository replays and updates the same run row, as the donor
    importer does.
    """

    commit = graph_commit(parsed)
    with transaction.atomic():
        course = _course(parsed.course)
        units = UnitImport(course, parsed.course.modules)
        run = _start_run(parsed, source, commit)

        try:
            course, counts = _apply(parsed, checkout, commit, course, units)
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


def _start_run(parsed, source, commit):
    owner, _, name = source.repo_name.rpartition("/")
    run = CurriculumImportRun.objects.filter(
        source_uuid=source.pk, commit_sha=commit, parser_version=parsed.parser_version
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
    return run


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


def _apply(parsed, checkout, commit, course, units) -> tuple[Course, dict]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0}
    graph = parsed.course

    action = write_values(course, course_values(graph, commit, checkout))
    counts[action] += 1
    _sync_instructors(course, graph)
    units.park()

    # Cohorts resolve placements from the completed top-level module tree.
    seen_module_ids: set[str] = set()
    top_level_by_ref: dict[str, Module] = {}
    _apply_module_tree(
        course,
        graph.modules,
        units,
        parent=None,
        commit=commit,
        checkout=checkout,
        counts=counts,
        seen=seen_module_ids,
        top_level_by_ref=top_level_by_ref,
    )
    counts["deleted"] += units.delete_stale()
    counts["deleted"] += delete_stale(
        Module.objects.filter(course=course).exclude(source_content_id__isnull=True),
        seen_module_ids,
    )

    seen_cohort_ids = set()
    for cohort_graph in graph.cohorts:
        cohort = _cohort(course, cohort_graph)
        seen_cohort_ids.add(cohort_graph.content_id)
        counts[write_values(cohort, cohort_values(cohort_graph, commit, checkout))] += 1
        counts["deleted"] += _apply_placements(cohort, cohort_graph, top_level_by_ref)
    counts["deleted"] += delete_stale(
        Cohort.objects.filter(course=course).exclude(source_content_id__isnull=True),
        seen_cohort_ids,
    )
    return course, counts


def _apply_module_tree(
    course: Course,
    module_graphs,
    units,
    *,
    parent: Module | None,
    commit,
    checkout,
    counts: dict,
    seen: set,
    top_level_by_ref: dict,
    depth: int = 0,
) -> None:
    for position, module_graph in enumerate(module_graphs):
        _apply_module_graph(
            course,
            module_graph,
            units,
            parent,
            position,
            commit,
            checkout,
            counts,
            seen,
            top_level_by_ref,
            depth,
        )


def _apply_module_graph(
    course, graph, units, parent, position, commit, checkout, counts, seen, top_level_by_ref, depth
):
    module = _module(course, parent, graph)
    seen.add(graph.content_id)
    counts[write_values(module, module_values(graph, parent, position, commit, checkout))] += 1
    units.visited_modules.add(module.pk)
    if depth == 0:
        top_level_by_ref[graph.content_id or graph.slug] = module
    child_position = 0
    for sibling in graph.siblings:
        if isinstance(sibling, UnitGraph):
            _apply_direct_unit(sibling, module, units, commit, checkout, counts)
            continue
        _apply_module_graph(
            course,
            sibling,
            units,
            module,
            child_position,
            commit,
            checkout,
            counts,
            seen,
            top_level_by_ref,
            depth + 1,
        )
        child_position += 1


def _apply_direct_unit(graph, module, units, commit, checkout, counts):
    unit = units.resolve(graph)
    values = unit_values(graph, commit, checkout)
    values["module_id"] = module.pk
    counts[write_values(unit, values)] += 1
    units.seen.add(unit.pk)


def _apply_placements(cohort: Cohort, cohort_graph, top_level_by_ref: dict) -> int:
    """Sync this cohort's :class:`CohortModule` placements; return the deleted count.

    ``module_refs is None`` means the source declared no cohort-specific placement --
    every existing placement row is removed so the cohort falls back to the course's
    full default tree (:meth:`Cohort.effective_modules`). A (possibly empty) tuple means
    the source is authoritative for this cohort's placements: rows are synced to match it
    exactly, position by position.
    """

    if cohort_graph.module_refs is None:
        stale = CohortModule.objects.filter(cohort=cohort)
        count = stale.count()
        stale.delete()
        return count

    seen_module_pks: set = set()
    for position, ref in enumerate(cohort_graph.module_refs):
        module = top_level_by_ref.get(ref)
        if module is None:
            raise CurriculumParseError(
                f"{cohort_graph.source_path or cohort_graph.slug}: "
                f"placement references unknown top-level module {ref!r}"
            )
        seen_module_pks.add(module.pk)
        CohortModule.objects.update_or_create(
            cohort=cohort, module=module, defaults={"sort_order": position}
        )
    stale = CohortModule.objects.filter(cohort=cohort).exclude(module_id__in=seen_module_pks)
    count = stale.count()
    stale.delete()
    return count


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


def _module(course: Course, parent: Module | None, graph) -> Module:
    module = None
    if graph.content_id:
        module = Module.objects.filter(course=course, source_content_id=graph.content_id).first()
    if module is None:
        module = Module.objects.filter(course=course, parent=parent, slug=graph.slug).first()
    if module is None:
        module = Module(course=course, slug=graph.slug)
    module.source_content_id = graph.content_id
    return module


def write_values(instance, values) -> str:
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


def delete_stale(queryset, seen_ids: set) -> int:
    seen = {str(value) for value in seen_ids if value is not None}
    stale = [
        row
        for row in queryset
        if row.source_content_id is None or str(row.source_content_id) not in seen
    ]
    for row in stale:
        row.delete()
    return len(stale)
