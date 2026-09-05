from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
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
