"""Unification regression: API and curriculum Studio issue through the shared service.

Both paths must create/update the ``Certificate`` row, mirror the url onto
``Enrollment.certificate_url``, fire the ``certificate_issued`` hook, and leave the
certificate visible on the learner view (``coursework_certificate``), which reads the
``Certificate`` row first with the legacy enrollment column as fallback.
"""

import pytest
from django.urls import include, path, reverse

from community_base.accounts.models import User
from community_base.api.models import APIKey
from community_base.curriculum.models import Certificate, Enrollment
from testproject.urls import urlpatterns as _base_urlpatterns
from tests.curriculum.test_models import make_cohort, make_course

pytestmark = pytest.mark.django_db

urlpatterns = [
    path("courses/", include("community_base.coursework.urls")),
] + list(_base_urlpatterns)


@pytest.fixture(autouse=True)
def learner_urlconf(settings):
    settings.ROOT_URLCONF = __name__


def _staff_api_keys():
    user = User.objects.create_user(email="cert-unify-api@example.com", is_staff=True)
    _, write_key = APIKey.create_for_user(
        user=user,
        name="Cert unify writer",
        scopes=["curriculum.write"],
        kind=APIKey.Kind.STAFF,
    )
    return write_key


def _learner_view_url(course, cohort):
    return reverse("coursework_certificate", args=[course.slug, cohort.slug])


def test_api_issue_mirrors_hook_and_shows_on_learner_view(client, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_ISSUED": lambda **event: seen.append(event),
    }
    course = make_course(slug="unify-api-course", title="Unify API Course")
    cohort = make_cohort(course, slug="unify-api-cohort", title="Unify API cohort")
    learner = User.objects.create_user(email="unify-api-learner@example.com")
    Enrollment.objects.create(user=learner, cohort=cohort)
    url = "https://certs.example.com/unify-api.pdf"

    issued = client.post(
        f"/api/v1/courses/{course.slug}/certificates",
        {"user_email": learner.email, "cohort_slug": cohort.slug, "url": url},
        content_type="application/json",
        headers={"Authorization": f"Bearer {_staff_api_keys()}"},
    )

    assert issued.status_code == 200
    certificate = Certificate.objects.get(enrollment__user=learner, enrollment__cohort=cohort)
    assert certificate.url == url
    enrollment = Enrollment.objects.get(user=learner, cohort=cohort)
    assert enrollment.certificate_url == url
    assert len(seen) == 1
    assert seen[0]["certificate"] == certificate

    client.force_login(learner)
    response = client.get(_learner_view_url(course, cohort))

    assert response.status_code == 200
    assert response.context["certificate"] == certificate
    assert response.context["certificate_url"] == url


def test_studio_issue_mirrors_hook_and_shows_on_learner_view(client, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_ISSUED": lambda **event: seen.append(event),
    }
    course = make_course(slug="unify-studio-course", title="Unify Studio Course")
    cohort = make_cohort(course, slug="unify-studio-cohort", title="Unify Studio cohort")
    learner = User.objects.create_user(email="unify-studio-learner@example.com")
    enrollment = Enrollment.objects.create(user=learner, cohort=cohort)
    staff = User.objects.create_user(email="unify-studio-staff@example.com", is_staff=True)
    client.force_login(staff)
    url = "https://certs.example.com/unify-studio.pdf"

    issued = client.post(
        reverse("curriculum_studio_certificate_issue", args=[enrollment.pk]),
        {"url": url},
    )

    assert issued.status_code == 302
    certificate = Certificate.objects.get(enrollment=enrollment)
    assert certificate.url == url
    enrollment.refresh_from_db()
    assert enrollment.certificate_url == url
    assert len(seen) == 1
    assert seen[0]["certificate"] == certificate

    client.force_login(learner)
    response = client.get(_learner_view_url(course, cohort))

    assert response.status_code == 200
    assert response.context["certificate"] == certificate
    assert response.context["certificate_url"] == url
