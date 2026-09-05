from __future__ import annotations

import json
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.urls import get_resolver

from community_base.api.openapi import build_document


class Command(BaseCommand):
    help = "Generate or check the registered Community Base OpenAPI document"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--check", action="store_true")
        parser.add_argument("--output", default="api/openapi.json")

    def handle(self, *args, **options):
        _ = get_resolver().url_patterns
        output = Path(options["output"])
        rendered = f"{json.dumps(build_document(), indent=2, sort_keys=True)}\n"
        if options["check"]:
            if not output.exists() or output.read_text() != rendered:
                raise CommandError(f"OpenAPI document is stale: {output}")
            self.stdout.write(self.style.SUCCESS("OpenAPI document is current"))
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        self.stdout.write(str(output))
