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

from community_base.content_sync.documents import MANIFEST_NAME
from community_base.content_sync.kinds.layouts import COURSE_MANIFEST
from community_base.content_sync.parsers import SourceItem
from community_base.curriculum.importing import apply_curriculum_graph
from community_base.curriculum.models import CurriculumImportRun
from community_base.curriculum.parsers import (
    PARSER_VERSION,
    check_read,
    course_collections,
    parse_course,
    read_courses,
)


class CourseParser:
    """One SourceItem per course collection; the graph is applied in upsert."""

    parser_version = PARSER_VERSION

    def __init__(self):
        self._checkout = None
        self._result = None
        self._collections = {}
        self._seen_content_ids = set()

    def discover(self, checkout, source):
        """Read the repository once and name every course collection it declares.

        A repository with no ``content.yaml`` is not a content repository and
        yields nothing, so a source that lost its content still reaches
        ``soft_delete_missing``. A repository that has one and fails a rule of
        the format raises instead: a parse failure must never mass-draft
        content.
        """

        self._checkout = checkout
        self._seen_content_ids = set()
        self._result = None
        self._collections = {}
        if not any(path.as_posix() == MANIFEST_NAME for path in checkout.files()):
            return ()
        self._result = read_courses(checkout)
        collections = course_collections(self._result)
        if not collections:
            check_read(self._result)
            return ()
        items = []
        for collection in collections:
            key = collection.path or "."
            self._collections[key] = collection
            path = f"{collection.path}/{COURSE_MANIFEST}" if collection.path else COURSE_MANIFEST
            items.append(SourceItem(key=key, path=path, data={}))
        return tuple(items)

    def upsert(self, item, source, media):
        from community_base.content_sync.orchestration import UpsertResult

        parsed = self._parse(item)
        if parsed.course.content_id:
            self._seen_content_ids.add(parsed.course.content_id)
        course, counts = apply_curriculum_graph(parsed, source, self._checkout)
        if counts["created"]:
            action = "created"
        elif counts["updated"]:
            action = "updated"
        else:
            action = "unchanged"
        return UpsertResult(course, action)

    def soft_delete_missing(self, seen_keys: set, source):
        """Soft-delete this source's courses that vanished from the repository.

        Rows refreshed by successful runs of this source carry that run's
        commit, so the run history scopes ownership exactly; rows from other
        sources carry different commits and are never touched. When the
        latest run did not succeed (a parse failure must never mass-draft
        content) this is a no-op.
        """

        runs = CurriculumImportRun.objects.filter(
            source_uuid=source.pk, parser_version=self.parser_version
        ).order_by("-created_at")
        latest = runs.first()
        if latest is None or latest.state != CurriculumImportRun.State.SUCCEEDED:
            return ()
        reference_commits = list(
            CurriculumImportRun.objects.filter(
                source_uuid=source.pk,
                parser_version=self.parser_version,
                state=CurriculumImportRun.State.SUCCEEDED,
                created_at__lt=latest.created_at,
            )
            .values_list("commit_sha", flat=True)
            .distinct()
        )
        if latest.state == CurriculumImportRun.State.SUCCEEDED:
            reference_commits.append(latest.commit_sha)
        if not reference_commits:
            return ()
        from community_base.curriculum.models import Course

        # Only courses this parser version actually imported for the source
        # can be drafted; commit shas alone are not a safe scope when two
        # sources share one repository (as local fixture checkouts do).
        managed_slugs = list(
            CurriculumImportRun.objects.filter(
                source_uuid=source.pk,
                parser_version=self.parser_version,
                state=CurriculumImportRun.State.SUCCEEDED,
            )
            .values_list("source_stable_id", flat=True)
            .distinct()
        )
        candidates = Course.objects.filter(
            slug__in=managed_slugs, source_commit_sha__in=reference_commits
        )
        seen = {str(value) for value in self._seen_content_ids if value is not None}
        drafted = [
            course
            for course in candidates
            if course.source_content_id is None or str(course.source_content_id) not in seen
        ]
        for course in drafted:
            course.status = "draft"
            course.save(update_fields=["status", "updated_at"])
        return drafted

    def _parse(self, item):
        return parse_course(
            self._result,
            self._collections[item.key],
            commit_sha=getattr(self._checkout, "commit_sha", None) or None,
        )
