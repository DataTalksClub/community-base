import pytest
from django.core.exceptions import ImproperlyConfigured

from community_base.coursework.integrations import generate_certificate_artifact
from tests.coursework.test_models import coursework_cohort, enrollment_for

pytestmark = pytest.mark.django_db


def test_raises_when_unconfigured(settings):
    settings.COMMUNITY_BASE = {}
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="seam-unset@example.com")

    with pytest.raises(ImproperlyConfigured):
        generate_certificate_artifact(enrollment)


def test_calls_the_configured_callable_with_enrollment_and_certificate(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_GENERATOR": lambda enrollment, certificate: (
            seen.append((enrollment, certificate)) or "https://certs.example.com/a.pdf"
        ),
    }
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="seam-call@example.com")

    url = generate_certificate_artifact(enrollment, "sentinel-certificate")

    assert url == "https://certs.example.com/a.pdf"
    assert seen == [(enrollment, "sentinel-certificate")]


def test_resolves_a_dotted_path_string(settings):
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_GENERATOR": "tests.coursework.integrations_fixture.fake_generator",
    }
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="seam-path@example.com")

    url = generate_certificate_artifact(enrollment)

    assert url == "https://certs.example.com/dotted-path.pdf"


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "ftp://certs.example.com/a.pdf",
        "http://user:pass@certs.example.com/a.pdf",
        "",
        None,
        123,
    ],
)
def test_rejects_an_invalid_returned_url(settings, value):
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_GENERATOR": lambda enrollment, certificate: value,
    }
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort, email="seam-invalid@example.com")

    with pytest.raises(ImproperlyConfigured):
        generate_certificate_artifact(enrollment)
