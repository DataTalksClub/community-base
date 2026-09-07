"""``content_sync`` parser adapters for the two curriculum layouts.

Both adapters produce the same graph type (``community_base.curriculum.source``)
and apply it through the shared importer. They sniff their layout in
``discover``, so registering both is harmless on any content source.

The sync orchestration is sequential per source, so the adapters keep the
active checkout on the instance between ``discover`` and ``upsert``.
"""

from community_base.content_sync.parsers import SourceItem
from community_base.curriculum.importing import apply_curriculum_graph
from community_base.curriculum.models import CurriculumImportRun
from community_base.curriculum.parsers_aisl import parse_aisl_course
from community_base.curriculum.parsers_dtc import (
    looks_like_course_repository,
    parse_dtc_course_repository,
)


class BaseCurriculumParser:
    """One SourceItem per course; the graph is parsed and applied in upsert."""

    parser_version = ""

    def __init__(self):
        self._checkout = None
        self._seen_content_ids = set()

    def discover(self, checkout, source):
        self._checkout = checkout
        self._seen_content_ids = set()
        return tuple(self._items(checkout))

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

    def _items(self, checkout):
        raise NotImplementedError

    def _parse(self, item):
        raise NotImplementedError


class AislCourseParser(BaseCurriculumParser):
    """Parser for the AISL ``course.yaml`` layout."""

    parser_version = "aisl-course-yaml-1"

    def _items(self, checkout):
        for path in checkout.files():
            # A root-level course.yaml is the DTC course repository layout,
            # which the DTC parser owns; AISL course directories are nested.
            if len(path.parts) > 1 and path.parts[-1] == "course.yaml":
                yield SourceItem(key=path.parts[0], path=path, data={})

    def _parse(self, item):
        return parse_aisl_course(self._checkout, item.path.as_posix())


class DtcCourseRepositoryParser(BaseCurriculumParser):
    """Parser for the DTC course repository contract."""

    parser_version = "dtc-course-repository-1"

    def _items(self, checkout):
        if looks_like_course_repository(checkout):
            yield SourceItem(key="course-repository", path="course.yaml", data={})

    def _parse(self, item):
        return parse_dtc_course_repository(self._checkout)
