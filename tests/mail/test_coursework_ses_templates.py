"""Coursework purposes are safe file-template names in the transitional SES backend."""

from unittest.mock import patch

import pytest
from django.db import transaction

from community_base.coursework.notifications import (
    POOL_READY_PURPOSE,
    REVIEW_ASSIGNED_PURPOSE,
    REVIEW_RECEIVED_PURPOSE,
    REVIEW_WINDOW_EXPIRED_PURPOSE,
)
from community_base.coursework.reminders import (
    HOMEWORK_DEADLINE_PURPOSE,
    PEER_REVIEW_DEADLINE_PURPOSE,
    PROJECT_SUBMISSION_DEADLINE_PURPOSE,
)
from community_base.mail.models import EmailDelivery
from community_base.mail.service import send

PURPOSES = (
    REVIEW_ASSIGNED_PURPOSE,
    POOL_READY_PURPOSE,
    REVIEW_RECEIVED_PURPOSE,
    REVIEW_WINDOW_EXPIRED_PURPOSE,
    HOMEWORK_DEADLINE_PURPOSE,
    PROJECT_SUBMISSION_DEADLINE_PURPOSE,
    PEER_REVIEW_DEADLINE_PURPOSE,
)


class FakeSES:
    def __init__(self):
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": f"fake-{len(self.calls)}"}


@pytest.fixture
def coursework_template_dir(settings, tmp_path):
    settings.COMMUNITY_BASE = {
        **settings.COMMUNITY_BASE,
        "MAIL_BACKEND": "ses_local",
        "MAIL_TEMPLATE_DIR": tmp_path,
        "SITE_URL": "https://example.test",
        "STUDIO_TITLE": "Example Studio",
    }
    for purpose in PURPOSES:
        (tmp_path / f"{purpose}.md").write_text(
            f"---\nsubject: Notice {purpose}\n---\nHello {{{{ name }}}}!\n"
        )
    return tmp_path


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("purpose", PURPOSES)
def test_coursework_purpose_delivers_from_file_template(coursework_template_dir, purpose):
    ses = FakeSES()
    with patch("community_base.mail.backends.ses_local.configured_client", return_value=ses):
        with transaction.atomic():
            delivery = send(
                purpose,
                "learner@example.test",
                {"name": "Ada"},
                f"{purpose}:fixture",
                sender="sender@example.test",
            )

    delivery.refresh_from_db()
    assert delivery.state == EmailDelivery.State.PROVIDER_ACCEPTED
    assert len(ses.calls) == 1
    simple = ses.calls[0]["Content"]["Simple"]
    assert simple["Subject"]["Data"] == f"Notice {purpose}"
    assert "Hello Ada!" in simple["Body"]["Html"]["Data"]
    assert "Hello Ada!" in simple["Body"]["Text"]["Data"]
