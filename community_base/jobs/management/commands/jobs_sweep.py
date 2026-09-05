from django.core.management.base import BaseCommand

from community_base.jobs.runner import sweep_expired_jobs


class Command(BaseCommand):
    help = "Recover durable jobs whose execution leases expired"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        recovered, dead = sweep_expired_jobs(limit=options["limit"])
        self.stdout.write(f"recovered={recovered} dead={dead}")
