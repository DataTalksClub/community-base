from django.core.management.base import BaseCommand

from community_base.jobs.operations import run_due


class Command(BaseCommand):
    help = "Submit due durable job intents to the configured local backend"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        found, submitted = run_due(limit=options["limit"])
        self.stdout.write(f"found={found} submitted={submitted}")
