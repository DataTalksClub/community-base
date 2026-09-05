from django.core.management.base import BaseCommand, CommandError

from community_base.jobs.scheduling import (
    desired_local_schedules,
    parse_stored_kwargs,
    schedule_changes,
)
from community_base.kernel.conf import get


class Command(BaseCommand):
    help = "Synchronize registered durable job schedules with the local backend"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        backend = get("JOBS_BACKEND")
        if backend == "sync":
            self.stdout.write("sync backend has no persistent scheduler")
            return
        if backend != "django_q":
            raise CommandError(f"sync_schedules does not support the {backend!r} backend")
        try:
            from django_q.models import Schedule  # type: ignore[import-untyped]
        except ImportError as error:
            raise CommandError(
                "The django_q jobs backend requires community-base[django_q]."
            ) from error

        existing = {
            row.name: {
                "func": row.func,
                "cron": row.cron,
                "kwargs": parse_stored_kwargs(row.kwargs),
                "repeats": row.repeats,
            }
            for row in Schedule.objects.filter(name__startswith="community-base:")
        }
        changes = schedule_changes(existing)
        for action, name in changes:
            self.stdout.write(f"{action}: {name}")
        if options["dry_run"]:
            return
        for action, name in changes:
            if action == "delete":
                Schedule.objects.filter(name=name).delete()
        actions = {name: action for action, name in changes}
        for spec in desired_local_schedules():
            if actions[spec.name] == "unchanged":
                continue
            row, created = Schedule.objects.update_or_create(
                name=spec.name,
                defaults={
                    "func": spec.func,
                    "schedule_type": Schedule.CRON,
                    "cron": spec.cron,
                    "repeats": -1,
                    "kwargs": spec.kwargs,
                },
            )
            if not created:
                row.next_run = row.calculate_next_run()
                row.save(update_fields=("next_run",))
