import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace

from community_base.content_sync.models import SyncLog
from community_base.curriculum.site_adaptation import (
    CourseSiteBoundaryError,
    CourseSiteRefusal,
    CourseSiteResult,
    PreparedCourse,
)
from tests.curriculum.utils import AISL_CONTENT, DTC_REPO

ACTIVE_SITE_RENDERER = ContextVar("active_site_renderer", default=None)


class RecordingCourseAdapter:
    def __init__(self):
        self.boundary_slugs = set()
        self.boundary_error = CourseSiteBoundaryError
        self.fail_after_slugs = set()
        self.incompatible_slugs = set()
        self.refused_slugs = set()
        self.suppressed_slugs = set()
        self.warning_slugs = set()
        self.events = []
        self.reports = []

    def prepare(self, context, collection, parsed):
        slug = parsed.course.slug
        self.events.append(("prepare", slug))
        if slug in self.boundary_slugs:
            raise self.boundary_error(f"checkout refused for {slug}")
        if slug in self.refused_slugs:
            raise CourseSiteRefusal(f"policy refused {slug}")
        course = self._prepared_course(parsed.course)
        return PreparedCourse(replace(parsed, course=course), {"slug": slug})

    def _prepared_course(self, course):
        if course.slug in self.incompatible_slugs:
            return replace(course, slug=f"wrong-{course.slug}")
        return replace(course, cover_image_url=f"site:{course.cover_image_url}")

    @contextmanager
    def apply_scope(self, context, prepared):
        slug = prepared.state["slug"]
        self.events.append(("scope-enter", slug))
        try:
            yield
        except RuntimeError:
            if slug not in self.suppressed_slugs:
                raise
        finally:
            self.events.append(("scope-exit", slug))

    def after_apply(self, context, prepared, core):
        slug = prepared.state["slug"]
        self.events.append(("after", slug))
        if slug in self.fail_after_slugs or slug in self.suppressed_slugs:
            raise RuntimeError(f"post apply failed for {slug}")
        warnings = ()
        if slug in self.warning_slugs:
            warnings = (f"render warning for {slug}",)
        detail = {"slug": slug, "action": core.action}
        return CourseSiteResult(core.action, {}, detail, warnings)

    def report(self, context, *, results, errors, drafted, totals):
        self.events.append(("report", results, errors, drafted, dict(totals)))
        self.reports.append((results, errors, drafted, dict(totals)))


class TransactionalCourseAdapter(RecordingCourseAdapter):
    @contextmanager
    def apply_scope(self, context, prepared):
        slug = prepared.state["slug"]
        self.events.append(("scope-enter", slug))
        SyncLog.objects.create(source=context.source, warnings=[f"pre:{slug}"])
        token = ACTIVE_SITE_RENDERER.set(slug)
        try:
            yield
        finally:
            ACTIVE_SITE_RENDERER.reset(token)
            self.events.append(("scope-exit", slug))

    def after_apply(self, context, prepared, core):
        slug = prepared.state["slug"]
        SyncLog.objects.create(source=context.source, warnings=[f"post:{slug}"])
        return super().after_apply(context, prepared, core)


def two_course_repository_with_homework(tmp_path):
    root = tmp_path / "two-courses"
    root.mkdir()
    shutil.copytree(DTC_REPO, root / "dtc")
    (root / "dtc" / "content.yaml").unlink()
    shutil.copytree(AISL_CONTENT / "courses" / "agents", root / "agents")
    (root / "content.yaml").write_text(
        "schema_version: 1\n"
        "collections:\n"
        "  - kind: course\n"
        "    path: dtc\n"
        "  - kind: course\n"
        "    path: agents\n"
    )
    return root
