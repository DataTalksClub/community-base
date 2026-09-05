import json
import uuid
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone

from community_base.jobs.ingress import sign_body
from community_base.jobs.models import JobIntent
from community_base.kernel.conf import get


class Command(BaseCommand):
    help = "Round-trip a signed request through the durable job ingress"

    def handle(self, *args, **options):
        secret = get("RELAY_WEBHOOK_SECRET")
        if not isinstance(secret, str) or not secret:
            raise CommandError("RELAY_WEBHOOK_SECRET must be configured")
        site_url = urlparse(get("SITE_URL"))
        if site_url.scheme not in {"http", "https"} or not site_url.netloc:
            raise CommandError("SITE_URL must be an absolute HTTP URL")
        nonce = uuid.uuid4()
        intent = JobIntent.objects.create(
            handler="system.noop",
            key_hash=nonce.hex + nonce.hex,
            payload={},
            payload_hash="0" * 64,
            available_at=timezone.now(),
        )
        body = json.dumps(
            {"intent_id": str(intent.id)}, sort_keys=True, separators=(",", ":")
        ).encode()
        timestamp = str(int(timezone.now().timestamp()))
        response = Client().post(
            "/internal/jobs/run",
            data=body,
            content_type="application/json",
            secure=site_url.scheme == "https",
            headers={
                "Host": site_url.netloc,
                "X-Relay-Task-Id": str(uuid.uuid4()),
                "X-Relay-Correlation-Id": str(uuid.uuid4()),
                "X-Relay-Timestamp": timestamp,
                "X-Relay-Signature": sign_body(body, timestamp, secret),
            },
        )
        intent.refresh_from_db()
        if response.status_code != 200 or intent.status != JobIntent.Status.SUCCEEDED:
            raise CommandError("signed job ingress self-test failed")
        self.stdout.write("OK")
