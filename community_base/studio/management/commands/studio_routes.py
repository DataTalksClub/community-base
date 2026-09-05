from django.core.management.base import BaseCommand, CommandError

from community_base.studio.route_checks import route_partition_errors


class Command(BaseCommand):
    help = "Check that every mounted Studio route has exactly one navigation owner."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Validate the route partition")

    def handle(self, *args, **options):
        errors = route_partition_errors()
        if errors:
            for error in errors:
                self.stderr.write(error)
            raise CommandError(f"Studio route partition has {len(errors)} error(s)")
        self.stdout.write("OK")
