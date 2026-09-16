"""Certificate artifact generation: a site-supplied external-service seam.

The package must not import from any site application, and banner-generator (the service this
calls) is site infrastructure, not package infrastructure. Mirrors
``community_base.events.integrations.hooks.generate_banner`` exactly rather than inventing a
second configuration mechanism: a dotted path to a site-owned callable, resolved through
``COURSEWORK_CERTIFICATE_GENERATOR``. A site's callable owns its own endpoint and token entirely
(for AI Shipping Labs: ``BANNER_GENERATOR_FUNCTION_URL``/``BANNER_GENERATOR_AUTH_TOKEN``, read
through that site's own ``IntegrationSetting``/``get_config``); this module never sees either.
"""

from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve


def _callback(setting):
    configured = get(setting)
    if configured is None:
        return None
    return resolve(configured) if isinstance(configured, str) else configured


def _safe_certificate_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise ImproperlyConfigured("Certificate generator returned an invalid URL.")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ImproperlyConfigured("Certificate generator returned an invalid URL.")
    return value


def generate_certificate_artifact(enrollment, certificate=None) -> str:
    """Call the site-configured certificate generator; return a validated artifact URL.

    Raises ``ImproperlyConfigured`` when ``COURSEWORK_CERTIFICATE_GENERATOR`` is unset --
    unlike ``events.generate_banner``'s silent ``None``, a learner explicitly requesting a
    certificate with nothing configured to generate one is an operator error worth surfacing
    loudly, the same choice ``events.process_recording`` already makes for a comparable case.

    The configured callable returns a plain URL string, exactly like ``EVENT_BANNER_GENERATOR``.
    Whether it is a PDF, an image, or a page offering both is a site decision this seam
    deliberately does not fix (open question in DataTalksClub/community-base#256):
    ``curriculum.Certificate.url`` holds whichever URL comes back either way, so nothing here
    needs to change once that question is answered.
    """

    callback = _callback("COURSEWORK_CERTIFICATE_GENERATOR")
    if callback is None:
        raise ImproperlyConfigured(
            "COURSEWORK_CERTIFICATE_GENERATOR is not configured; cannot generate a certificate "
            "artifact."
        )
    value = callback(enrollment, certificate)
    return _safe_certificate_url(value)
