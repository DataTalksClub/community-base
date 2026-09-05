"""Signed GitHub webhook receiver for content sync."""

import hashlib
import hmac
import json
import re

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from community_base.content_sync.models import ContentSource, WebhookLog
from community_base.content_sync.queue import queue_source_sync

MAX_WEBHOOK_BYTES = 1_000_000
SIGNATURE_PATTERN = re.compile(r"^sha256=([0-9a-f]{64})$")


def _response(message, status):
    return JsonResponse({"message": message}, status=status)


@csrf_exempt
def github_webhook(request):
    if request.method != "POST":
        return _response("Method not allowed", 405)
    try:
        content_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        return _response("Invalid content length", 400)
    if content_length > MAX_WEBHOOK_BYTES:
        return _response("Payload too large", 413)
    body = request.body
    if len(body) > MAX_WEBHOOK_BYTES:
        return _response("Payload too large", 413)
    try:
        payload = json.loads(body)
        repo_name = payload["repository"]["full_name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _response("Invalid payload", 400)
    if not isinstance(payload, dict) or not isinstance(repo_name, str):
        return _response("Invalid payload", 400)
    try:
        source = ContentSource.objects.get(repo_name=repo_name)
    except ContentSource.DoesNotExist:
        return _response("Unknown content source", 404)
    if not _valid_signature(request, source.webhook_secret, body):
        return _response("Invalid signature", 401)

    delivery = request.headers.get("X-GitHub-Delivery", "").strip()
    event_type = request.headers.get("X-GitHub-Event", "").strip()[:200]
    if not delivery or len(delivery) > 200 or not event_type:
        return _response("Missing webhook metadata", 400)
    delivery_digest = hashlib.sha256(delivery.encode()).hexdigest()
    deduplication_key = f"github:{delivery_digest}"
    safe_payload = {
        "repository": repo_name,
        "ref": str(payload.get("ref", ""))[:300],
        "after": str(payload.get("after", ""))[:40],
    }

    with transaction.atomic():
        webhook, created = WebhookLog.objects.get_or_create(
            deduplication_key=deduplication_key,
            defaults={
                "service": "github",
                "event_type": event_type,
                "payload": safe_payload,
                "attempts": 1,
            },
        )
        if not created:
            return _response("Duplicate delivery", 200)

        should_sync = _should_sync(event_type, payload) and source.is_enabled
        if should_sync:
            queue_source_sync(source, key=f"webhook:{delivery_digest}")
        now = timezone.now()
        webhook.processed = True
        webhook.processed_at = now
        webhook.save(update_fields=("processed", "processed_at"))
        ContentSource.objects.filter(pk=source.pk).update(last_webhook_at=now)
    return _response("Sync queued" if should_sync else "Delivery accepted", 202)


def _valid_signature(request, secret, body):
    supplied = request.headers.get("X-Hub-Signature-256", "")
    match = SIGNATURE_PATTERN.fullmatch(supplied)
    if match is None or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, match.group(1))


def _should_sync(event_type, payload):
    if event_type != "push":
        return False
    default_branch = payload.get("repository", {}).get("default_branch")
    return isinstance(default_branch, str) and payload.get("ref") == f"refs/heads/{default_branch}"
