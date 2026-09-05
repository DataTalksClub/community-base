from django.core.management.base import BaseCommand, CommandError

from community_base.content_sync.models import ContentSource
from community_base.content_sync.orchestration import sync_content_source


class Command(BaseCommand):
    help = "Synchronize one or all configured content sources."

    def add_arguments(self, parser):
        parser.add_argument("--from-disk", dest="from_disk")
        parser.add_argument("--source", dest="source_slug")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        sources = (
            ContentSource.objects.all()
            if options["force"]
            else ContentSource.objects.filter(is_enabled=True)
        )
        if options["source_slug"]:
            sources = sources.filter(slug=options["source_slug"])
        sources = list(sources)
        if not sources:
            raise CommandError("No matching enabled content source")
        if options["from_disk"] and len(sources) != 1:
            raise CommandError("--from-disk requires exactly one source; pass --source")

        failed = False
        for source in sources:
            log = sync_content_source(
                source,
                repo_dir=options["from_disk"],
                force=options["force"],
            )
            self.stdout.write(
                f"{source.slug}: {log.status} "
                f"created={log.items_created} updated={log.items_updated} "
                f"unchanged={log.items_unchanged} deleted={log.items_deleted}"
            )
            failed = failed or log.status in {"failed", "partial"}
        if failed:
            raise CommandError("One or more content sources did not sync successfully")
