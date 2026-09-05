from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.utils import timezone


@dataclass
class FakeResponse:
    status_code: int
    document: object

    def json(self):
        if isinstance(self.document, Exception):
            raise self.document
        return copy.deepcopy(self.document)


class FakeRelayTransport:
    def __init__(self, api_key="relay-test-key"):
        self.api_key = api_key
        self.calls = []
        self.tasks = {}
        self.task_keys = {}
        self.schedules = {}
        self.next_response = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        if self.next_response is not None:
            response = self.next_response
            self.next_response = None
            if isinstance(response, Exception):
                raise response
            return response
        if kwargs["headers"].get("Authorization") != f"Bearer {self.api_key}":
            return FakeResponse(401, {"error": {"code": "unauthorized"}})
        path = urlsplit(url).path
        payload = kwargs.get("json")
        if method == "POST" and path == "/api/tasks":
            return self._submit_task(payload)
        if method == "GET" and path.startswith("/api/tasks/"):
            task_id = path.rsplit("/", 1)[-1]
            task = self.tasks.get(task_id)
            return FakeResponse(200, task) if task else FakeResponse(404, {})
        if method == "POST" and path.endswith("/complete"):
            return self._finish_task(path, "succeeded")
        if method == "POST" and path.endswith("/fail"):
            return self._finish_task(path, "failed")
        if method == "GET" and path == "/api/schedules":
            return FakeResponse(200, {"schedules": list(self.schedules.values())})
        if method == "POST" and path == "/api/schedules":
            return self._upsert_schedule(payload)
        if method == "DELETE" and path.startswith("/api/schedules/"):
            return self._delete_schedule(path.rsplit("/", 1)[-1])
        if method == "GET" and path == "/health/ready":
            return FakeResponse(200, {"status": "ready", "service": "relay"})
        return FakeResponse(404, {"error": {"code": "not_found"}})

    def _submit_task(self, payload):
        key = payload["idempotency_key"]
        existing_id = self.task_keys.get(key)
        if existing_id:
            task = self.tasks[existing_id]
            same = task["type"] == payload["type"] and task["request"] == payload
            return FakeResponse(200 if same else 409, task if same else {})
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "type": payload["type"],
            "idempotency_key": key,
            "status": "queued",
            "request": copy.deepcopy(payload),
        }
        self.tasks[task_id] = task
        self.task_keys[key] = task_id
        return FakeResponse(202, task | {"idempotent_replay": False})

    def _finish_task(self, path, status):
        task_id = path.split("/")[-2]
        task = self.tasks.get(task_id)
        if task is None:
            return FakeResponse(404, {})
        task["status"] = status
        return FakeResponse(200, {"id": task_id, "status": status})

    def _upsert_schedule(self, payload):
        existing = next(
            (row for row in self.schedules.values() if row["name"] == payload["name"]), None
        )
        created = existing is None
        schedule_id = str(uuid.uuid4()) if created else existing["id"]
        task = {
            "url": payload["url"],
            "payload": payload.get("params", {}),
            "timeout_seconds": float(payload.get("timeout_seconds", 30)),
        }
        row = {
            "id": schedule_id,
            "name": payload["name"],
            "cron": payload["cron"],
            "type": payload["type"],
            "task": task,
            "enabled": payload.get("enabled", True),
            "next_run_at": "2026-09-05T12:00:00+00:00",
            "last_run_at": None,
            "last_success_at": None,
        }
        self.schedules[schedule_id] = row
        return FakeResponse(201 if created else 200, row)

    def _delete_schedule(self, schedule_id):
        row = self.schedules.get(schedule_id)
        if row is None:
            return FakeResponse(404, {})
        row["enabled"] = False
        return FakeResponse(200, row)

    def deliver(self, task_id, django_client, webhook_secret):
        from community_base.jobs.ingress import sign_body

        task = self.tasks[task_id]
        body = json.dumps(task["request"]["params"], sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(timezone.now().timestamp()))
        response = django_client.post(
            urlsplit(task["request"]["url"]).path,
            data=body,
            content_type="application/json",
            headers={
                "X-Relay-Task-Id": task_id,
                "X-Relay-Correlation-Id": task["request"].get("correlation_id", str(uuid.uuid4())),
                "X-Relay-Timestamp": timestamp,
                "X-Relay-Signature": sign_body(body, timestamp, webhook_secret),
            },
        )
        if response.status_code == 200:
            task["status"] = "succeeded"
        elif response.status_code == 202:
            task["status"] = "running"
            task["lease_seconds"] = response.json()["lease_seconds"]
        else:
            task["status"] = "failed"
        return response
