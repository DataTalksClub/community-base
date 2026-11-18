"""Move a project between states by hand."""

from django.core.management.base import BaseCommand, CommandError

from community_base.coursework.models import Project
from community_base.coursework.project_state import (
    ProjectStateError,
    parse_state,
    set_project_state,
)
from community_base.curriculum.models import Course


def move_project(
    course_slug: str, project_slug: str, state: str, *, cohort_slug: str | None = None
):
    course = Course.objects.filter(slug=course_slug).first()
    if course is None:
        raise CommandError(f'Course "{course_slug}" not found.')
    qs = Project.objects.filter(cohort__course=course, slug=project_slug).select_related("cohort")
    if cohort_slug:
        qs = qs.filter(cohort__slug=cohort_slug)
    matches = list(qs[:2])
    if not matches:
        raise CommandError(f'Project "{project_slug}" not found in course "{course_slug}".')
    if len(matches) > 1:
        raise CommandError(
            f'Multiple cohorts have project "{project_slug}" in "{course_slug}"; pass --cohort.'
        )
    project = matches[0]
    try:
        previous = set_project_state(project, parse_state(state))
    except ProjectStateError as error:
        raise CommandError(str(error)) from error
    return project, previous


class Command(BaseCommand):
    help = "Set a project state (collecting_submissions, peer_reviewing, completed, closed)."

    def add_arguments(self, parser):
        parser.add_argument("course_slug")
        parser.add_argument("project_slug")
        parser.add_argument("state")
        parser.add_argument("--cohort", default=None, help="Optional cohort slug.")

    def handle(self, *args, **options):
        project, previous = move_project(
            options["course_slug"],
            options["project_slug"],
            options["state"],
            cohort_slug=options["cohort"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{project.slug}: {previous} -> {project.state} ({project.get_state_display()})"
            )
        )
