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
        self.contacts = {}
        self.contacts_by_email = {}
        self.contact_tags = {}
        self.subscriptions = {}
        self.preferences = {}
        self.verification_tokens = {}
        self.verification_sends = []
        self.subscription_changes = []
        self._next_contact_id = 0

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
        if path in {"/api/contacts", "/api/contacts/status", "/api/contacts/preferences"}:
            return self._contacts_request(method, path, payload, kwargs.get("params") or {})
        if path.startswith("/api/contacts/"):
            return self._contact_item_request(method, path, payload, kwargs.get("params") or {})
        if path.startswith("/api/subscriptions/"):
            return self._subscriptions_request(method, path, payload)
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

    def _contacts_request(self, method, path, payload, params):
        if path == "/api/contacts":
            if method != "POST":
                return self._method_not_allowed(["POST"])
            return self._upsert_contact(payload or {})
        source = params if method == "GET" else (payload or {})
        if path == "/api/contacts/status":
            scope, error = self._scope(source)
            if error:
                return error
            return FakeResponse(
                200,
                self._contact_status_document(
                    scope,
                    requested_email=str(source.get("email", "")),
                    contact_id=self.contacts_by_email.get(scope["email"]),
                ),
            )
        if path == "/api/contacts/preferences":
            if method not in {"GET", "PUT"}:
                return self._method_not_allowed(["GET", "PUT"])
            return self._contact_preferences(method, source)
        return FakeResponse(404, {"error": {"code": "not_found"}})

    def _contact_item_request(self, method, path, payload, params):
        suffix = path.removeprefix("/api/contacts/")
        contact_id_text, _, action = suffix.partition("/")
        if not contact_id_text.isdigit():
            return FakeResponse(404, {"error": {"code": "not_found"}})
        contact_id = int(contact_id_text)
        if action == "tags" and method == "PUT":
            return self._replace_tags(contact_id, payload or {})
        if action.startswith("tags/") and method in {"POST", "DELETE"}:
            return self._contact_tag(contact_id, action.removeprefix("tags/"), method, params)
        return FakeResponse(404, {"error": {"code": "not_found"}})

    def _subscriptions_request(self, method, path, payload):
        if method != "POST":
            return self._method_not_allowed(["POST"])
        body = payload or {}
        if path == "/api/subscriptions/subscribe":
            return self._subscribe(body)
        if path == "/api/subscriptions/unsubscribe":
            return self._unsubscribe(body)
        if path == "/api/subscriptions/request-verification":
            return self._request_verification(body)
        if path == "/api/subscriptions/confirm":
            return self._confirm_verification(body)
        return FakeResponse(404, {"error": {"code": "not_found"}})

    def _method_not_allowed(self, allowed):
        return FakeResponse(
            405, {"error": {"code": "method_not_allowed", "allowed_methods": allowed}}
        )

    def _validation_error(self, fields, status=400):
        return FakeResponse(status, {"error": {"code": "validation_error", "fields": fields}})

    def _scope(self, source, *, require_email=True):
        errors = {}
        email = source.get("email")
        if require_email and (not isinstance(email, str) or not email.strip()):
            errors["email"] = "required"
        if not isinstance(source.get("audience"), str) or not source["audience"].strip():
            errors["audience"] = "required"
        if not isinstance(source.get("client"), str) or not source["client"].strip():
            errors["client"] = "required"
        if errors:
            return None, self._validation_error(errors)
        email_text = str(email).strip().lower() if require_email else ""
        scope = {"email": email_text, "audience": source["audience"], "client": source["client"]}
        return scope, None

    def _upsert_contact(self, payload):
        scope, error = self._scope(payload)
        if error:
            return error
        contact_id = self.contacts_by_email.get(scope["email"])
        if contact_id is None:
            self._next_contact_id += 1
            contact_id = self._next_contact_id
            self.contacts_by_email[scope["email"]] = contact_id
            self.contacts[contact_id] = {
                "email": scope["email"],
                "verified_at": None,
                "email_validation": {"status": "unknown", "reason": "", "validated_at": None},
                "global_unsubscribed_at": None,
                "hard_bounced_at": None,
                "complained_at": None,
            }
        contact = self.contacts[contact_id]
        if payload.get("verified") is True:
            contact["verified_at"] = contact["verified_at"] or self._stamp()
        if payload.get("verified") is False:
            contact["verified_at"] = None
        for flag, field in {
            "global_unsubscribed": "global_unsubscribed_at",
            "hard_bounced": "hard_bounced_at",
            "complained": "complained_at",
        }.items():
            if flag in (payload.get("suppression") or {}):
                contact[field] = self._stamp() if payload["suppression"][flag] else None
        validation = payload.get("email_validation")
        if isinstance(validation, dict):
            contact["email_validation"] = {
                "status": validation.get("status", "unknown"),
                "reason": str(validation.get("reason", "")),
                "validated_at": validation.get("validated_at"),
            }
        key = (contact_id, scope["audience"], scope["client"])
        subscription = self.subscriptions.get(key)
        previously_unsubscribed = (
            subscription is not None and subscription["status"] == "unsubscribed"
        )
        status = payload.get("status") or (subscription or {}).get("status") or "pending"
        if status not in {"pending", "subscribed", "unsubscribed"}:
            return self._validation_error({"status": "invalid"})
        previous = subscription or {}
        self.subscriptions[key] = {
            "status": status,
            "verified_at": contact["verified_at"]
            if payload.get("verified")
            else previous.get("verified_at"),
            "unsubscribed_at": self._stamp()
            if status == "unsubscribed"
            else previous.get("unsubscribed_at"),
        }
        if previously_unsubscribed and status == "subscribed":
            self.subscription_changes.append(
                {**scope, "contact_id": contact_id, "status": "subscribed"}
            )
        self.contact_tags[(contact_id, scope["audience"])] = {
            self._tag_slug(tag) for tag in (payload.get("tags") or [])
        }
        return FakeResponse(200, self._contact_document(contact_id, scope))

    def _contact_status_document(self, scope, requested_email="", contact_id=None):
        audience = scope["audience"]
        client = scope["client"]
        contact = self.contacts.get(contact_id) if contact_id is not None else None
        subscription = self.subscriptions.get((contact_id, audience, client)) if contact else None
        visible = contact is not None and subscription is not None
        if not visible:
            return {
                "contact_id": None,
                "email": requested_email,
                "exists": False,
                "verified": False,
                "verified_at": None,
                "email_validation": {"status": "unknown", "reason": "", "validated_at": None},
                "global_unsubscribed": False,
                "hard_bounced": False,
                "complained": False,
                "audience": {"slug": audience, **self._subscription_document(None)},
                "client": {"slug": client, **self._subscription_document(None)},
                "can_send_marketing": False,
                "can_send_transactional": False,
            }
        audience_subscription = self.subscriptions.get((contact_id, audience, "*")) or {}
        return {
            "contact_id": contact_id,
            "email": contact["email"],
            "exists": True,
            "verified": contact["verified_at"] is not None,
            "verified_at": contact["verified_at"],
            "email_validation": dict(contact["email_validation"]),
            "global_unsubscribed": contact["global_unsubscribed_at"] is not None,
            "hard_bounced": contact["hard_bounced_at"] is not None,
            "complained": contact["complained_at"] is not None,
            "audience": {"slug": audience, **self._subscription_document(audience_subscription)},
            "client": {"slug": client, **self._subscription_document(subscription)},
            "can_send_marketing": (
                contact["verified_at"] is not None
                and subscription["status"] == "subscribed"
                and audience_subscription.get("status") != "unsubscribed"
                and contact["global_unsubscribed_at"] is None
                and contact["hard_bounced_at"] is None
                and contact["complained_at"] is None
            ),
            "can_send_transactional": contact["hard_bounced_at"] is None
            and contact["complained_at"] is None,
        }

    def _subscription_document(self, subscription):
        if not subscription:
            return {
                "subscribed": False,
                "status": None,
                "verified": False,
                "verified_at": None,
                "unsubscribed_at": None,
                "unsubscribe_reason": "",
            }
        return {
            "subscribed": subscription["status"] == "subscribed",
            "status": subscription["status"],
            "verified": subscription.get("verified_at") is not None,
            "verified_at": subscription.get("verified_at"),
            "unsubscribed_at": subscription.get("unsubscribed_at"),
            "unsubscribe_reason": "",
        }

    def _contact_document(self, contact_id, scope):
        document = self._contact_status_document(
            scope, contact_id=contact_id, requested_email=self.contacts[contact_id]["email"]
        )
        slugs = self.contact_tags.get((contact_id, scope["audience"]), set())
        document["tags"] = sorted(slugs)
        return document

    def _existing_contact(self, contact_id, source):
        if contact_id not in self.contacts:
            return None, self._validation_error({"contact_id": "not_found"}, status=404)
        scope, error = self._scope(source, require_email=False)
        if error:
            return None, error
        if (contact_id, scope["audience"], scope["client"]) not in self.subscriptions:
            return None, self._validation_error({"contact_id": "not_found"}, status=404)
        return scope, None

    def _replace_tags(self, contact_id, payload):
        scope, error = self._existing_contact(contact_id, payload)
        if error:
            return error
        tags = payload.get("tags")
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            return self._validation_error({"tags": "must_be_list"})
        self.contact_tags[(contact_id, scope["audience"])] = {self._tag_slug(tag) for tag in tags}
        return FakeResponse(200, self._contact_document(contact_id, scope))

    def _contact_tag(self, contact_id, tag_slug, method, params):
        scope, error = self._existing_contact(contact_id, params)
        if error:
            return error
        slugs = self.contact_tags.setdefault((contact_id, scope["audience"]), set())
        slug = self._tag_slug(tag_slug)
        if method == "POST":
            slugs.add(slug)
        else:
            slugs.discard(slug)
        return FakeResponse(200, self._contact_document(contact_id, scope))

    def _contact_preferences(self, method, source):
        scope, error = self._scope(source)
        if error:
            return error
        contact_id = self.contacts_by_email.get(scope["email"])
        if method == "PUT":
            # The real endpoint upserts the contact before storing preferences.
            if contact_id is None:
                contact_id = self._create_contact(scope["email"])
            key = (contact_id, scope["audience"], scope["client"])
            return self._update_preferences(contact_id, key, self.preferences.get(key, {}), source)
        stored = (
            self.preferences.get((contact_id, scope["audience"], scope["client"]), {})
            if contact_id is not None
            else {}
        )
        requested = [
            tag.strip() for tag in str(source.get("category_tags") or "").split(",") if tag.strip()
        ] or sorted(stored)
        return FakeResponse(200, self._preferences_document(contact_id, stored, requested))

    def _update_preferences(self, contact_id, key, stored, source):
        categories = source.get("categories")
        if not isinstance(categories, list):
            return self._validation_error({"categories": "must_be_list"})
        parsed = []
        for index, item in enumerate(categories):
            if not isinstance(item, dict) or not isinstance(item.get("tag"), str):
                return self._validation_error({f"categories.{index}": "must_be_object"})
            if not isinstance(item.get("enabled"), bool):
                return self._validation_error({f"categories.{index}.enabled": "must_be_boolean"})
            parsed.append(item)
        contact = self.contacts.get(contact_id)
        suppressed = contact is not None and any(
            contact[field] is not None
            for field in ("global_unsubscribed_at", "hard_bounced_at", "complained_at")
        )
        if suppressed and any(item["enabled"] for item in parsed):
            return self._validation_error(
                {"categories": "suppressed_contact_cannot_be_enabled"}, status=409
            )
        for item in parsed:
            stored[item["tag"]] = {
                "label": str(item.get("label", "")),
                "enabled": item["enabled"],
            }
        self.preferences[key] = stored
        return FakeResponse(
            200,
            self._preferences_document(contact_id, stored, [item["tag"] for item in parsed]),
        )

    def _preferences_document(self, contact_id, stored, requested_tags):
        contact = self.contacts.get(contact_id)
        reasons = []
        if contact is not None:
            if contact["global_unsubscribed_at"] is not None:
                reasons.append("global_unsubscribed")
            if contact["hard_bounced_at"] is not None:
                reasons.append("hard_bounce")
            if contact["complained_at"] is not None:
                reasons.append("complaint")
        categories = [
            {
                "tag": tag,
                "label": stored.get(tag, {}).get("label") or tag.replace("-", " ").title(),
                "enabled": stored.get(tag, {}).get("enabled", True),
            }
            for tag in requested_tags
        ]
        return {
            "global_unsubscribed": bool(reasons) and "global_unsubscribed" in reasons,
            "suppressed": bool(reasons),
            "suppression_reasons": reasons,
            "categories": categories,
        }

    def _subscribe(self, body):
        scope, error = self._scope(body)
        if error:
            return error
        upsert = self._upsert_contact(
            {
                "email": scope["email"],
                "audience": scope["audience"],
                "client": scope["client"],
                "status": "subscribed",
                "tags": body.get("tags") or [],
            }
        )
        if upsert.status_code != 200:
            return upsert
        contact_id = self.contacts_by_email[scope["email"]]
        if body.get("category") is not None:
            self._set_preference(contact_id, scope, str(body["category"]), True)
        self.subscription_changes.append(
            {**scope, "contact_id": contact_id, "status": "subscribed"}
        )
        return FakeResponse(200, self._contact_document(contact_id, scope))

    def _unsubscribe(self, body):
        scope, error = self._scope(body)
        if error:
            return error
        scope_name = body.get("scope")
        if scope_name not in {"client", "audience", "global"}:
            return self._validation_error({"scope": "invalid"})
        contact_id = self.contacts_by_email.get(scope["email"])
        if contact_id is None:
            contact_id = self._create_contact(scope["email"])
        contact = self.contacts[contact_id]
        if scope_name == "global":
            contact["global_unsubscribed_at"] = contact["global_unsubscribed_at"] or self._stamp()
        else:
            if scope_name == "audience":
                # Relay stores audience-level subscriptions with a null client.
                key = (contact_id, scope["audience"], "*")
            else:
                key = (contact_id, scope["audience"], scope["client"])
            subscription = self.subscriptions.get(key) or {
                "status": "pending",
                "verified_at": None,
                "unsubscribed_at": None,
            }
            subscription["status"] = "unsubscribed"
            subscription["unsubscribed_at"] = self._stamp()
            self.subscriptions[key] = subscription
        if body.get("category") is not None:
            self._set_preference(contact_id, scope, str(body["category"]), False)
        self.subscription_changes.append(
            {**scope, "contact_id": contact_id, "status": "unsubscribed", "scope": scope_name}
        )
        document = self._contact_status_document(
            scope, contact_id=contact_id, requested_email=scope["email"]
        )
        document["scope"] = scope_name
        return FakeResponse(200, document)

    def _set_preference(self, contact_id, scope, tag, enabled):
        key = (contact_id, scope["audience"], scope["client"])
        stored = self.preferences.setdefault(key, {})
        stored[tag] = {"label": tag.replace("-", " ").title(), "enabled": enabled}

    def _request_verification(self, body):
        scope, error = self._scope(body)
        if error:
            return error
        category = body.get("category")
        template_key = body.get("template_key")
        if not isinstance(category, str) or not category.strip():
            return self._validation_error({"category": "required"})
        if not isinstance(template_key, str) or not template_key.strip():
            return self._validation_error({"template_key": "required"})
        token = f"verify-{uuid.uuid4().hex}"
        self.verification_tokens[token] = {
            "email": scope["email"],
            "audience": scope["audience"],
            "client": scope["client"],
            "category": category,
        }
        self.verification_sends.append(
            {
                "email": scope["email"],
                "audience": scope["audience"],
                "client": scope["client"],
                "template_key": template_key,
                "context": {
                    "confirm_url": f"https://relay.example.com/subscribe/confirm/{token}",
                    "verification_token": token,
                    "category": category,
                },
            }
        )
        return FakeResponse(
            200,
            {
                "status": "verification_requested",
                "email": scope["email"],
                "audience": scope["audience"],
                "client": scope["client"],
                "category": category,
                "template_key": template_key,
            },
        )

    def _confirm_verification(self, body):
        token = body.get("token") if isinstance(body, dict) else None
        issued = self.verification_tokens.get(token) if isinstance(token, str) else None
        if issued is None:
            return self._validation_error({"token": "invalid"})
        contact_id = self.contacts_by_email.get(issued["email"])
        if contact_id is None:
            contact_id = self._create_contact(issued["email"])
        self._set_preference(contact_id, issued, issued["category"], True)
        stored = self.preferences[(contact_id, issued["audience"], issued["client"])]
        preference = stored[issued["category"]]
        return FakeResponse(
            200,
            {
                "email": issued["email"],
                "audience": issued["audience"],
                "client": issued["client"],
                "category": {
                    "tag": issued["category"],
                    "label": preference["label"],
                    "enabled": preference["enabled"],
                },
            },
        )

    def _create_contact(self, email):
        self._next_contact_id += 1
        contact_id = self._next_contact_id
        self.contacts_by_email[email] = contact_id
        self.contacts[contact_id] = {
            "email": email,
            "verified_at": None,
            "email_validation": {"status": "unknown", "reason": "", "validated_at": None},
            "global_unsubscribed_at": None,
            "hard_bounced_at": None,
            "complained_at": None,
        }
        return contact_id

    @staticmethod
    def _tag_slug(value):
        return str(value).strip().lower()

    @staticmethod
    def _stamp():
        return datetime.now().astimezone().isoformat()

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
