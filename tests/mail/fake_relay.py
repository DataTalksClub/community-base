from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit


@dataclass
class FakeResponse:
    status_code: int
    document: object

    def json(self):
        if isinstance(self.document, Exception):
            raise self.document
        return copy.deepcopy(self.document)


class FakeMailRelayTransport:
    def __init__(self, api_key: str = "relay-test-key"):
        self.api_key = api_key
        self.calls = []
        self.messages = {}
        self.idempotency_keys = {}
        self.next_response = None
        self.templates = {}

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
        if method == "POST" and path == "/api/transactional/send":
            return self._send(kwargs["json"])
        if method == "GET" and path == "/api/transactional/messages":
            return FakeResponse(200, {"messages": list(self.messages.values())})
        if method == "GET" and path == "/api/transactional/templates":
            return FakeResponse(200, {"templates": list(self.templates.values())})
        if path.startswith("/api/transactional/templates/"):
            return self._template_request(method, path, kwargs.get("json"))
        return FakeResponse(404, {"error": {"code": "not_found"}})

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
            version = {
                "template_key": key,
                "version": number,
                "status": "published",
            }
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
