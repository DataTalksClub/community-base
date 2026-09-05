from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from community_base.jobs.dispatch import hash_key, hash_payload
from community_base.jobs.models import JobIntent
from community_base.jobs.registry import RegistryError, handler_definition, registered_schedules
from community_base.jobs.runner import DEFAULT_LEASE_SECONDS, run_intent
from community_base.kernel.conf import get
from community_base.kernel.context import is_safe_external_context_id

SIGNATURE_TOLERANCE_SECONDS = 300
MAX_INGRESS_BODY_BYTES = 32_768


@csrf_exempt
def run_job(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _error("method_not_allowed", 405)

    body = request.body
    if len(body) > MAX_INGRESS_BODY_BYTES:
        return _error("body_too_large", 400)
    auth_error = _verify_request(request, body)
    if auth_error is not None:
        return auth_error

    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return _error("invalid_payload", 400)
    if not isinstance(document, dict):
        return _error("invalid_payload", 400)
    intent_id = _intent_id(document.get("intent_id"))
    schedule_name = document.get("schedule_name")
    if (intent_id is None) == (not isinstance(schedule_name, str)):
        return _error("invalid_payload", 400)

    task_id = request.headers["X-Relay-Task-Id"]
    correlation_id = request.headers["X-Relay-Correlation-Id"]
    try:
        with transaction.atomic():
            bound = JobIntent.objects.select_for_update().filter(external_id=task_id).first()
            if bound is not None:
                first_delivery = (
                    intent_id == bound.id
                    and bound.status == JobIntent.Status.SUBMITTED
                    and bound.attempts == 0
                )
                if not first_delivery:
                    return _error("replayed_task", 409)
                intent = bound
                if not intent.correlation_id:
                    JobIntent.objects.filter(id=intent.id, correlation_id="").update(
                        correlation_id=correlation_id,
                        updated_at=timezone.now(),
                    )
                    intent.correlation_id = correlation_id
            elif intent_id is None:
                intent = _create_scheduled_intent(schedule_name, task_id, correlation_id)
                if intent is None:
                    return _error("unknown_schedule", 404)
                intent_id = intent.id
            else:
                intent = JobIntent.objects.select_for_update().filter(id=intent_id).first()
                if intent is None:
                    return _error("unknown_intent", 404)
                if intent.external_id:
                    return _error("intent_already_submitted", 409)
            try:
                definition = handler_definition(intent.handler)
            except RegistryError:
                return _error("unknown_handler", 409)
            if not intent.external_id:
                updates = {"external_id": task_id, "updated_at": timezone.now()}
                if not intent.correlation_id:
                    updates["correlation_id"] = correlation_id
                if intent.status == JobIntent.Status.PENDING:
                    updates["status"] = JobIntent.Status.SUBMITTED
                JobIntent.objects.filter(id=intent.id, external_id="").update(**updates)
    except IntegrityError:
        return _error("replayed_task", 409)

    result = run_intent(intent_id, worker_id=f"relay:{task_id}")
    if definition.chunked:
        return JsonResponse(
            {"status": "accepted", "result": result, "lease_seconds": DEFAULT_LEASE_SECONDS},
            status=202,
        )
    return JsonResponse({"status": "ok", "result": result})


def sign_body(body: bytes, timestamp: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def _intent_id(value) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _create_scheduled_intent(
    schedule_name: str, task_id: str, correlation_id: str
) -> JobIntent | None:
    definitions = {item.name: item for item in registered_schedules()}
    scheduled = definitions.get(schedule_name)
    if scheduled is None:
        return None
    return JobIntent.objects.create(
        handler=scheduled.handler,
        key_hash=hash_key(f"relay-schedule:{task_id}"),
        payload=scheduled.payload,
        payload_hash=hash_payload(scheduled.payload),
        status=JobIntent.Status.SUBMITTED,
        available_at=timezone.now(),
        correlation_id=correlation_id,
        external_id=task_id,
    )


def _verify_request(request: HttpRequest, body: bytes) -> JsonResponse | None:
    secret = get("RELAY_WEBHOOK_SECRET")
    if not isinstance(secret, str) or not secret:
        return _error("ingress_not_configured", 503)

    timestamp = request.headers.get("X-Relay-Timestamp", "")
    task_id = request.headers.get("X-Relay-Task-Id", "")
    correlation_id = request.headers.get("X-Relay-Correlation-Id", "")
    supplied = request.headers.get("X-Relay-Signature", "")
    try:
        age = abs(int(timezone.now().timestamp()) - int(timestamp))
    except ValueError:
        return _error("invalid_signature", 401)
    if age > SIGNATURE_TOLERANCE_SECONDS:
        return _error("stale_signature", 401)
    if not is_safe_external_context_id(task_id) or not is_safe_external_context_id(correlation_id):
        return _error("invalid_context", 401)
    expected = sign_body(body, timestamp, secret)
    if not hmac.compare_digest(supplied, expected):
        return _error("invalid_signature", 401)
    return None


def _error(code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": code}, status=status)
