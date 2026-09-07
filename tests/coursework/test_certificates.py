import pytest

from community_base.coursework.certificates import (
    certificate_for_enrollment,
    issue_certificate,
)
from community_base.curriculum.models import Certificate
from tests.coursework.test_models import coursework_cohort, enrollment_for

pytestmark = pytest.mark.django_db


def test_issue_certificate_creates_row_syncs_enrollment_and_fires_hook(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_ISSUED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="certified@example.com")

    certificate, issued = issue_certificate(
        enrollment, url="https://example.com/certificates/a.pdf"
    )

    assert issued is True
    assert certificate.enrollment_id == enrollment.id
    assert certificate.url == "https://example.com/certificates/a.pdf"
    assert Certificate.objects.filter(enrollment=enrollment).count() == 1
    enrollment.refresh_from_db()
    assert enrollment.certificate_url == "https://example.com/certificates/a.pdf"
    assert seen == [{"certificate": certificate, "enrollment": enrollment}]


def test_reissue_with_the_same_url_is_idempotent(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_ISSUED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="reissue@example.com")
    first, _issued = issue_certificate(enrollment, url="https://example.com/certificates/a.pdf")

    second, issued = issue_certificate(enrollment, url="https://example.com/certificates/a.pdf")

    assert issued is False
    assert second.id == first.id
    assert Certificate.objects.count() == 1
    assert seen == [{"certificate": first, "enrollment": enrollment}]


def test_changed_url_refires_the_hook_and_updates(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_ISSUED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="changed@example.com")
    first, _issued = issue_certificate(enrollment, url="https://example.com/certificates/a.pdf")

    second, issued = issue_certificate(enrollment, url="https://example.com/certificates/b.pdf")

    assert issued is True
    assert second.id == first.id
    second.refresh_from_db()
    assert second.url == "https://example.com/certificates/b.pdf"
    enrollment.refresh_from_db()
    assert enrollment.certificate_url == "https://example.com/certificates/b.pdf"
    assert len(seen) == 2
    assert seen[1]["certificate"].url == "https://example.com/certificates/b.pdf"


def test_certificate_for_enrollment_returns_none_then_the_row():
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="lookup@example.com")

    assert certificate_for_enrollment(enrollment) is None

    certificate, _issued = issue_certificate(
        enrollment, url="https://example.com/certificates/a.pdf"
    )
    assert certificate_for_enrollment(enrollment) == certificate
