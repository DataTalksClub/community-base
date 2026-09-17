from django.core.management.base import BaseCommand, CommandError

from community_base.content_sync.check import run_check


class Command(BaseCommand):
    help = "Check a content repository against the DataTalks.Club content format (FORMAT.md)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="the content repository to check")

    def handle(self, *args, **options):
        errors = run_check(options["path"], stdout=self.stdout)
        if errors:
            raise CommandError(f"{options['path']} does not match the content format")
