from django.core.management.base import BaseCommand, CommandError

from community_base.content_sync.models import ContentSource
from community_base.kernel.conf import get


class Command(BaseCommand):
    help = "Create or update content sources declared in COMMUNITY_BASE."

    def handle(self, *args, **options):
        declarations = get("CONTENT_SOURCES")
        if not isinstance(declarations, list):
            raise CommandError("COMMUNITY_BASE['CONTENT_SOURCES'] must be a list")
        for declaration in declarations:
            if not isinstance(declaration, dict):
                raise CommandError("Every content source declaration must be an object")
            required = {"slug", "repo_name", "webhook_secret"}
            if not required.issubset(declaration):
                raise CommandError("Content source requires slug, repo_name and webhook_secret")
            source, created = ContentSource.objects.update_or_create(
                slug=declaration["slug"],
                defaults={
                    "repo_name": declaration["repo_name"],
                    "webhook_secret": declaration["webhook_secret"],
                    "is_private": bool(declaration.get("is_private", False)),
                    "is_enabled": bool(declaration.get("is_enabled", True)),
                    "max_files": int(declaration.get("max_files", 1000)),
                },
            )
            source.full_clean()
            source.save()
            action = "created" if created else "updated"
            self.stdout.write(f"{source.slug}: {action}")
