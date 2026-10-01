"""The ``content_sync`` adapter for the one course parser.

The parser itself is :mod:`community_base.curriculum.parsers`, which maps the
document toolkit onto the graph and knows nothing about Django. This module is
the sync side of it: one repository read per ``discover``, one ``SourceItem``
per course collection, and the shared importer applied per course.

There is no layout sniffing left. A repository declares its courses in
``content.yaml`` (`FORMAT.md` section 3.1), so the adapter reads that manifest
instead of guessing a layout from where a ``course.yaml`` happens to sit -- the
guess that made a root-level ``course.yaml`` invisible.

The sync orchestration is sequential per source, so the adapter keeps the
active checkout and its read result on the instance between ``discover`` and
``upsert``.
"""

from dataclasses import replace

from django.apps import apps
from django.db import transaction

from community_base.content_sync.checkout import CheckoutError
from community_base.content_sync.documents import MANIFEST_NAME
from community_base.content_sync.kinds.layouts import COURSE_MANIFEST
from community_base.content_sync.parsers import SourceItem
from community_base.curriculum.importing import apply_curriculum_graph, graph_commit
from community_base.curriculum.parsers import (
    PARSER_VERSION,
    check_read,
    course_collections,
    parse_course,
    read_courses,
)
from community_base.curriculum.site_adaptation import (
    CourseCoreResult,
    CourseSiteBoundaryError,
    CourseSiteContext,
    CourseSitePartialError,
    CourseSiteRefusal,
    counts_action,
    get_course_site_adapter,
    merged_action,
    merged_counts,
    validate_prepared_course,
    validate_site_result,
)
from community_base.curriculum.site_cleanup import draft_missing_courses
from community_base.curriculum.source import CurriculumParseError

_MISSING = object()
_EMPTY_COUNTS = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0}


class CourseParser:
    """One SourceItem per course collection; the graph is applied in upsert."""

    parser_version = PARSER_VERSION

    def __init__(self):
        self._checkout = None
        self._result = None
        self._collections = {}
        self._seen_content_ids = set()
        self._site_adapter = None
        self._site_context = None
        self._site_failed = False
        self._site_partial = False
        self._site_totals = dict(_EMPTY_COUNTS)

    def discover(self, checkout, source):
        """Read the repository once and name every course collection it declares.

        A repository with no ``content.yaml`` is not a content repository and
        yields nothing, so a source that lost its content still reaches
        ``soft_delete_missing``. A repository that has one and fails a rule of
        the format raises instead: a parse failure must never mass-draft
        content.
        """

        self._start_discovery(checkout, source)
        if not any(path.as_posix() == MANIFEST_NAME for path in checkout.files()):
            return ()
        self._result = read_courses(checkout)
        self._site_context = replace(self._site_context, read_result=self._result)
        collections = course_collections(self._result)
        if not collections:
            check_read(self._result)
            return ()
        items = []
        for collection in collections:
            key = collection.path or "."
            self._collections[key] = collection
            path = COURSE_MANIFEST
            if collection.path:
                path = f"{collection.path}/{COURSE_MANIFEST}"
            items.append(SourceItem(key=key, path=path, data={}))
        return tuple(items)

    def _start_discovery(self, checkout, source):
        self._checkout = checkout
        self._seen_content_ids = set()
        self._result = None
        self._collections = {}
        self._site_adapter = get_course_site_adapter()
        self._site_context = CourseSiteContext(checkout, source, None, None)
        self._site_failed = False
        self._site_partial = False
        self._site_totals = dict(_EMPTY_COUNTS)

    def upsert(self, item, source, media):
        if self._site_adapter is not None:
            return self._upsert_adapted(item, media)
        return self._upsert_default(item, source)

    def _upsert_default(self, item, source):
        from community_base.content_sync.orchestration import UpsertResult

        parsed = self._parse(item)
        if parsed.course.content_id:
            self._seen_content_ids.add(parsed.course.content_id)
        graphs = self._read_homework(item, parsed)
        with transaction.atomic():
            course, counts = apply_curriculum_graph(parsed, source, self._checkout)
            for action, count in self._apply_homework(parsed, course, graphs).items():
                counts[action] = counts.get(action, 0) + count
        if counts["created"]:
            action = "created"
        elif counts["updated"]:
            action = "updated"
        else:
            action = "unchanged"
        return UpsertResult(course, action)

    def _upsert_adapted(self, item, media):
        context = replace(self._site_context, media=media)
        try:
            parsed = self._parse(item)
            graphs = self._read_homework(item, parsed)
        except (CheckoutError, CourseSiteBoundaryError) as error:
            self._report_fatal(context, item, error)
        except CurriculumParseError as error:
            return self._report_failure(context, item, error, authored=True)
        except Exception as error:  # adapter.report owns redacted source/traceback logging
            return self._report_failure(context, item, error, authored=False)
        prepared = self._prepare(context, item, parsed)
        if prepared is None:
            return self._failed_result()
        try:
            validate_prepared_course(parsed, prepared)
            core, site = self._apply_prepared(context, prepared, graphs)
        except (CheckoutError, CourseSiteBoundaryError) as error:
            self._report_fatal(context, item, error)
        except CurriculumParseError as error:
            return self._report_failure(context, item, error, authored=True)
        except Exception as error:  # adapter.report owns redacted source/traceback logging
            return self._report_failure(context, item, error, authored=False)
        return self._report_success(context, parsed, core, site)

    def _prepare(self, context, item, parsed):
        try:
            return self._site_adapter.prepare(context, self._collections[item.key], parsed)
        except (CheckoutError, CourseSiteBoundaryError) as error:
            self._report_fatal(context, item, error)
        except CourseSiteRefusal as error:
            self._report_failure(context, item, error, authored=True)
        except CurriculumParseError as error:
            self._report_failure(context, item, error, authored=True)
        except Exception as error:  # adapter.report owns redacted source/traceback logging
            self._report_failure(context, item, error, authored=False)
        return None

    def _apply_prepared(self, context, prepared, graphs):
        core = _MISSING
        site = _MISSING
        with transaction.atomic():
            with self._site_adapter.apply_scope(context, prepared):
                core = self._apply_core(prepared.curriculum, graphs)
                site = self._site_adapter.after_apply(context, prepared, core)
            if core is _MISSING or site is _MISSING:
                raise RuntimeError("Course site scope suppressed an apply failure")
            validate_site_result(site)
        return core, site

    def _apply_core(self, parsed, graphs):
        course, curriculum_counts = apply_curriculum_graph(
            parsed, self._site_context.source, self._checkout
        )
        homework_counts = self._apply_homework(parsed, course, graphs)
        counts = merged_counts(curriculum_counts, homework_counts)
        return CourseCoreResult(course, counts_action(counts), counts)

    def _report_success(self, context, parsed, core, site):
        from community_base.content_sync.orchestration import UpsertResult

        counts = merged_counts(core.counts, site.counts)
        self._site_totals = merged_counts(self._site_totals, counts)
        self._site_adapter.report(
            context, results=(site,), errors=(), drafted=(), totals=dict(self._site_totals)
        )
        if site.warnings:
            self._site_partial = True
        if parsed.course.content_id:
            self._seen_content_ids.add(parsed.course.content_id)
        return UpsertResult(core.course, merged_action(core.action, site.action))

    def _report_failure(self, context, item, error, *, authored):
        self._site_failed = True
        self._site_partial = True
        self._site_adapter.report(
            context,
            results=(),
            errors=((item, error, authored),),
            drafted=(),
            totals=dict(self._site_totals),
        )
        return self._failed_result()

    def _report_fatal(self, context, item, error):
        self._site_adapter.report(
            context,
            results=(),
            errors=((item, error, False),),
            drafted=(),
            totals=dict(self._site_totals),
        )
        raise error

    def _failed_result(self):
        from community_base.content_sync.orchestration import UpsertResult

        return UpsertResult(None, "unchanged")

    def soft_delete_missing(self, seen_keys: set, source):
        """Soft-delete this source's courses that vanished from the repository.

        Rows refreshed by successful runs of this source carry that run's
        commit, so the run history scopes ownership exactly; rows from other
        sources carry different commits and are never touched. When the
        latest run did not succeed (a parse failure must never mass-draft
        content) this is a no-op.
        """

        if self._site_adapter is not None and self._site_failed:
            raise CourseSitePartialError("Adapted course items failed; stale cleanup was skipped")
        drafted = draft_missing_courses(source, self.parser_version, self._seen_content_ids)
        if self._site_adapter is None:
            return drafted
        self._report_cleanup(drafted)
        if self._site_partial:
            raise CourseSitePartialError("Adapted course items completed with warnings")
        return drafted

    def _report_cleanup(self, drafted):
        cleanup_counts = dict(_EMPTY_COUNTS)
        cleanup_counts["deleted"] = len(drafted)
        self._site_totals = merged_counts(self._site_totals, cleanup_counts)
        self._site_adapter.report(
            self._site_context,
            results=(),
            errors=(),
            drafted=tuple(drafted),
            totals=dict(self._site_totals),
        )

    def _read_homework(self, item, parsed):
        """Import the manifests this course's cohorts bind (`FORMAT.md` 3.8, C7.11).

        Source validation runs even when the optional coursework app is not
        installed. Only its model writes are skipped in that configuration.
        The read result is the one this parser already holds, so no manifest
        is read twice and no second repository walk happens.
        """

        from community_base.coursework.manifests import read_cohort_homework

        return read_cohort_homework(self._result, self._collections[item.key], parsed)

    def _apply_homework(self, parsed, course, graphs) -> dict:
        if not apps.is_installed("community_base.coursework"):
            return {}
        from community_base.coursework.importing import apply_homework_graphs

        return apply_homework_graphs(
            course,
            graphs,
            commit=graph_commit(parsed),
            checkout=self._checkout,
        )

    def _parse(self, item):
        return parse_course(
            self._result,
            self._collections[item.key],
            commit_sha=getattr(self._checkout, "commit_sha", None) or None,
        )
