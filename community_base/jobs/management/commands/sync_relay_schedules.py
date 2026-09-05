from django.core.management.base import BaseCommand

from community_base.jobs.relay import configured_client
from community_base.jobs.relay_scheduling import sync_relay_schedules


class Command(BaseCommand):
    help = "Synchronize registered durable job schedules with Relay"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        changes = sync_relay_schedules(configured_client(), dry_run=options["dry_run"])
        for action, name, _schedule_id in changes:
            self.stdout.write(f"{action}: {name}")
