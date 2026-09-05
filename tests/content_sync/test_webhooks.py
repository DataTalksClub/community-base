import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import pytest
from django.urls import reverse

from community_base.content_sync.models import ContentSource, WebhookLog
from community_base.jobs.models import JobIntent


def signed_headers(body, secret="webhook-secret", delivery="delivery-one", event="push"):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_HUB_SIGNATURE_256": f"sha256={digest}",
        "HTTP_X_GITHUB_DELIVERY": delivery,
        "HTTP_X_GITHUB_EVENT": event,
    }


def payload(*, branch="main"):
    return {
        "repository": {"full_name": "owner/repo", "default_branch": "main"},
        "ref": f"refs/heads/{branch}",
        "after": "a" * 40,
        "sender": {"email": "must-not-be-stored@example.com"},
    }


@pytest.fixture
def source(db):
    return ContentSource.objects.create(
        slug="source", repo_name="owner/repo", webhook_secret="webhook-secret"
    )


@pytest.mark.django_db(transaction=True)
def test_signed_default_branch_push_creates_one_durable_source_job(client, source):
    body = json.dumps(payload()).encode()
    backend = Mock()
    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        response = client.post(
            reverse("cb_content_sync:github_webhook"),
            data=body,
            content_type="application/json",
            **signed_headers(body),
        )

    assert response.status_code == 202
    webhook = WebhookLog.objects.get()
    assert webhook.processed and webhook.attempts == 1
    assert webhook.payload == {
        "repository": "owner/repo",
        "ref": "refs/heads/main",
        "after": "a" * 40,
    }
    assert "email" not in repr(webhook.payload)
    intent = JobIntent.objects.get()
    assert intent.handler == "cb_content_sync.sync_source"
    assert intent.payload == {"source_id": str(source.pk), "force": False}
    source.refresh_from_db()
    assert source.last_webhook_at is not None


@pytest.mark.django_db(transaction=True)
def test_duplicate_delivery_does_not_create_second_job(client, source):
    body = json.dumps(payload()).encode()
    backend = Mock()
    with patch("community_base.jobs.dispatch.get_backend", return_value=backend):
        first = client.post(
            reverse("cb_content_sync:github_webhook"),
            data=body,
            content_type="application/json",
            **signed_headers(body),
        )
        second = client.post(
            reverse("cb_content_sync:github_webhook"),
            data=body,
            content_type="application/json",
            **signed_headers(body),
        )

    assert first.status_code == 202
    assert second.status_code == 200
    assert WebhookLog.objects.count() == 1
    assert JobIntent.objects.count() == 1


@pytest.mark.django_db
def test_invalid_signature_is_rejected_without_logging(client, source):
    body = json.dumps(payload()).encode()
    headers = signed_headers(body)
    headers["HTTP_X_HUB_SIGNATURE_256"] = f"sha256={'0' * 64}"

    response = client.post(
        reverse("cb_content_sync:github_webhook"),
        data=body,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 401
    assert not WebhookLog.objects.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("event,branch", [("ping", "main"), ("push", "feature")])
def test_irrelevant_signed_delivery_is_logged_without_a_job(client, source, event, branch):
    body = json.dumps(payload(branch=branch)).encode()

    response = client.post(
        reverse("cb_content_sync:github_webhook"),
        data=body,
        content_type="application/json",
        **signed_headers(body, event=event),
    )

    assert response.status_code == 202
    assert WebhookLog.objects.get().processed
    assert not JobIntent.objects.exists()


@pytest.mark.django_db
def test_unknown_repository_is_rejected(client):
    body = json.dumps(payload()).encode()

    response = client.post(
        reverse("cb_content_sync:github_webhook"),
        data=body,
        content_type="application/json",
        **signed_headers(body),
    )

    assert response.status_code == 404
