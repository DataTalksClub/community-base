from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from community_base.content_sync.models import ContentSource
from community_base.kernel.conf import get


class Command(BaseCommand):
    help = "Create or update content sources declared in COMMUNITY_BASE."

    def handle(self, *args, **options):
        declarations = get("CONTENT_SOURCES")
        if not isinstance(declarations, list):
            raise CommandError("COMMUNITY_BASE['CONTENT_SOURCES'] must be a list")
        with transaction.atomic():
            for declaration in declarations:
                if not isinstance(declaration, dict):
                    raise CommandError("Every content source declaration must be an object")
                required = {"slug", "repo_name", "webhook_secret"}
                if not required.issubset(declaration):
                    raise CommandError("Content source requires slug, repo_name and webhook_secret")
                source = ContentSource.objects.filter(slug=declaration["slug"]).first()
                created = source is None
                source = source or ContentSource(slug=declaration["slug"])
                source.repo_name = declaration["repo_name"]
                source.webhook_secret = declaration["webhook_secret"]
                source.is_private = _boolean(declaration, "is_private", False)
                source.is_enabled = _boolean(declaration, "is_enabled", True)
                try:
                    source.max_files = int(declaration.get("max_files", 1000))
                except (TypeError, ValueError):
                    raise CommandError("Content source max_files must be an integer") from None
                source.full_clean()
                source.save()
                action = "created" if created else "updated"
                self.stdout.write(f"{source.slug}: {action}")


def _boolean(declaration, key, default):
    value = declaration.get(key, default)
    if not isinstance(value, bool):
        raise CommandError(f"Content source {key} must be a boolean")
    return value
