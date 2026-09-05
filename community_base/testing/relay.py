from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import requests


@dataclass
class FakeResponse:
    status_code: int
    document: object = None

    def json(self):
        if isinstance(self.document, Exception):
            raise self.document
        return copy.deepcopy(self.document)


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    method: str
    url: str
    kwargs: dict[str, Any]

    def __getitem__(self, index):
        return (self.method, self.url, self.kwargs)[index]

    @property
    def params(self):
        return self.kwargs.get("params")

    @property
    def data(self):
        return self.kwargs.get("data")

    @property
    def timeout(self):
        return self.kwargs.get("timeout", 0.0)

    @property
    def allow_redirects(self):
        return bool(self.kwargs.get("allow_redirects", True))


class FakeRelay:
    """In-process transport implementing the package-pinned Relay contracts."""

    def __init__(
        self,
        status_code: int | None = None,
        *,
        api_key: str = "relay-test-key",
        error: Exception | None = None,
    ):
        self.api_key = api_key
        self.status_code = status_code
        self.error = error
        self.calls: list[RecordedRequest] = []
        self.tasks = {}
        self.task_keys = {}
        self.schedules = {}
        self.messages = {}
        self.idempotency_keys = {}
        self.templates = {}
        self.next_response = None

    @property
    def called(self) -> bool:
        return bool(self.calls)

    def request(self, method, url, **kwargs):
        self.calls.append(RecordedRequest(method, url, copy.deepcopy(kwargs)))
        if self.error is not None:
            raise self.error
        if self.next_response is not None:
            response = self.next_response
            self.next_response = None
            if isinstance(response, Exception):
                raise response
            return response
        path = urlsplit(url).path
        if path.startswith(("/t/o/", "/t/c/", "/unsubscribe/")):
            return FakeResponse(self.status_code if self.status_code is not None else 200)
        if kwargs.get("headers", {}).get("Authorization") != f"Bearer {self.api_key}":
            return FakeResponse(401, {"error": {"code": "unauthorized"}})
        payload = kwargs.get("json")
        if method == "POST" and path == "/api/tasks":
            return self._submit_task(payload)
        if method == "GET" and path == "/api/tasks":
            return FakeResponse(200, {"tasks": list(self.tasks.values())})
        if method == "GET" and path.startswith("/api/tasks/"):
            task = self.tasks.get(path.rsplit("/", 1)[-1])
            return FakeResponse(200, task) if task else FakeResponse(404, {})
        if method == "POST" and path.endswith("/complete"):
            return self._finish_task(path, "succeeded")
        if method == "POST" and path.endswith("/fail"):
            return self._finish_task(path, "retrying" if payload["retryable"] else "failed")
        if method == "GET" and path == "/api/schedules":
            return FakeResponse(200, {"schedules": list(self.schedules.values())})
        if method == "POST" and path == "/api/schedules":
            return self._upsert_schedule(payload)
        if method == "DELETE" and path.startswith("/api/schedules/"):
            return self._delete_schedule(path.rsplit("/", 1)[-1])
        if method == "GET" and path == "/health/ready":
            return FakeResponse(200, {"status": "ready", "service": "relay"})
        if method == "POST" and path == "/api/transactional/send":
            return self._send(payload)
        if method == "GET" and path == "/api/transactional/messages":
            return FakeResponse(200, {"messages": list(self.messages.values())})
        if method == "GET" and path == "/api/transactional/templates":
            return FakeResponse(200, {"templates": list(self.templates.values())})
        if path.startswith("/api/transactional/templates/"):
            return self._template_request(method, path, payload)
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
        row = {
            "id": schedule_id,
            "name": payload["name"],
            "cron": payload["cron"],
            "type": payload["type"],
            "task": {
                "url": payload["url"],
                "payload": payload.get("params", {}),
                "timeout_seconds": float(payload.get("timeout_seconds", 30)),
            },
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

    def _send(self, payload):
        existing_id = self.idempotency_keys.get(payload["idempotency_key"])
        if existing_id is not None:
            return FakeResponse(
                200,
                {
                    "message": copy.deepcopy(self.messages[existing_id]),
                    "idempotent_replay": True,
                    "enqueued": False,
                },
            )
        message_id = str(uuid.uuid4())
        message = {
            "id": message_id,
            "status": "queued",
            "template_key": payload["template_key"],
            "template_version": payload["template_version"],
            "idempotency_key": payload["idempotency_key"],
            "client_reference": payload["idempotency_key"],
            "reason_code": "",
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        self.messages[message_id] = message
        self.idempotency_keys[payload["idempotency_key"]] = message_id
        return FakeResponse(
            202,
            {"message": copy.deepcopy(message), "idempotent_replay": False, "enqueued": True},
        )

    def suppress_next(self, reason="hard_bounce"):
        self.next_response = FakeResponse(
            409,
            {
                "message": {"status": "suppressed"},
                "error": {"code": "transactional_suppressed", "reason": reason},
            },
        )

    def _template_request(self, method, path, payload):
        suffix = path.removeprefix("/api/transactional/templates/")
        key, _, action = suffix.partition("/")
        if method == "PUT" and not action:
            current = self.templates.get(key, {"key": key, "latest_version": None, "versions": []})
            current.update(copy.deepcopy(payload))
            current["key"] = key
            self.templates[key] = current
            return FakeResponse(200, {"template": self._public_template(current)})
        template = self.templates.get(key)
        if template is None:
            return FakeResponse(404, {"error": {"code": "not_found"}})
        if method == "GET" and action == "versions":
            return FakeResponse(200, {"versions": copy.deepcopy(template["versions"])})
        if method == "POST" and action == "publish":
            number = len(template["versions"]) + 1
            version = {"template_key": key, "version": number, "status": "published"}
            template["versions"].append(version)
            template["latest_version"] = number
            return FakeResponse(201, {"version": copy.deepcopy(version)})
        if method == "POST" and action == "preview":
            name = payload.get("context", {}).get("name", "reader")
            return FakeResponse(
                200,
                {
                    "rendered": {
                        "subject": f"Hello {name}",
                        "html_body": f"<p>Hello {name}</p>",
                        "text_body": f"Hello {name}",
                    }
                },
            )
        if method == "POST" and action == "test-send":
            version = payload.get("template_version") or template["latest_version"] or 1
            message_id = str(uuid.uuid4())
            return FakeResponse(
                202,
                {
                    "message": {
                        "id": message_id,
                        "status": "queued",
                        "template_key": key,
                        "template_version": version,
                    },
                    "idempotent_replay": False,
                },
            )
        return FakeResponse(404, {"error": {"code": "not_found"}})

    @staticmethod
    def _public_template(template):
        return {key: copy.deepcopy(value) for key, value in template.items() if key != "versions"}

    def deliver(self, task_id, django_client, webhook_secret):
        from community_base.testing import signed_relay_request

        task = self.tasks[task_id]
        signed = signed_relay_request(
            task["request"]["params"],
            webhook_secret,
            task_id=task_id,
            correlation_id=task["request"].get("correlation_id"),
        )
        response = django_client.post(
            urlsplit(task["request"]["url"]).path,
            **signed.django_kwargs(),
        )
        if response.status_code == 200:
            task["status"] = "succeeded"
        elif response.status_code == 202:
            task["status"] = "running"
            task["lease_seconds"] = response.json()["lease_seconds"]
        else:
            task["status"] = "failed"
        return response

    def post_callback(self, django_client, payload, webhook_secret, *, timestamp=None):
        from community_base.testing import signed_relay_request

        signed = signed_relay_request(payload, webhook_secret, timestamp=timestamp)
        return django_client.post("/internal/mail/callback", **signed.django_kwargs())


def unreachable_relay() -> FakeRelay:
    return FakeRelay(error=requests.ConnectionError("connection refused"))


def timing_out_relay() -> FakeRelay:
    return FakeRelay(error=requests.Timeout("read timed out"))
