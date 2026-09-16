import pytest
from django.core.exceptions import ImproperlyConfigured

from community_base.coursework.certificates import (
    CertificateEligibility,
    certificate_eligibility,
    certificate_for_enrollment,
    issue_certificate,
    request_certificate,
)
from community_base.coursework.models import ProjectSubmission
from community_base.curriculum.models import Certificate
from community_base.curriculum.services import mark_completed
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import make_project
from tests.curriculum.test_models import make_cohort, make_course, make_module, make_unit

pytestmark = pytest.mark.django_db


def eligibility_course_and_cohort(*, min_projects_to_pass=1):
    course = make_course(slug="cert-course")
    cohort = make_cohort(
        course,
        slug="cert-cohort",
        mode="cohort",
        min_projects_to_pass=min_projects_to_pass,
    )
    module = make_module(course)
    unit = make_unit(module)
    return course, cohort, unit


def make_passed_submission(project, enrollment):
    return ProjectSubmission.objects.create(
        project=project,
        student=enrollment.user,
        enrollment=enrollment,
        github_link="https://github.com/example/repo",
        commit_id="a" * 40,
        passed=True,
    )


def test_certificate_eligibility_reports_reasons_when_nothing_is_done():
    _course, cohort, _unit = eligibility_course_and_cohort()
    _user, enrollment = enrollment_for(cohort, email="ineligible@example.com")

    eligibility = certificate_eligibility(enrollment)

    assert eligibility.eligible is False
    assert any("units completed" in reason for reason in eligibility.reasons)
    assert any("projects passed" in reason for reason in eligibility.reasons)


def test_certificate_eligibility_true_once_units_and_projects_clear():
    course, cohort, unit = eligibility_course_and_cohort()
    _user, enrollment = enrollment_for(cohort, email="eligible@example.com")
    mark_completed(enrollment.user, unit, cohort=cohort)
    project = make_project(cohort)
    make_passed_submission(project, enrollment)

    eligibility = certificate_eligibility(enrollment)

    assert eligibility == CertificateEligibility(eligible=True, reasons=())


def test_certificate_eligibility_counts_only_this_enrollments_passed_non_volunteer_submissions():
    course, cohort, unit = eligibility_course_and_cohort(min_projects_to_pass=2)
    _user, enrollment = enrollment_for(cohort, email="partial@example.com")
    mark_completed(enrollment.user, unit, cohort=cohort)
    project = make_project(cohort)
    passed = make_passed_submission(project, enrollment)
    passed.volunteer_review_only = False
    passed.save()
    other_project = make_project(cohort, slug="second")
    ProjectSubmission.objects.create(
        project=other_project,
        student=enrollment.user,
        enrollment=enrollment,
        github_link="https://github.com/example/repo",
        commit_id="b" * 40,
        passed=False,
    )

    eligibility = certificate_eligibility(enrollment)

    assert eligibility.eligible is False
    assert "1 of 2 required projects passed." in eligibility.reasons


def test_request_certificate_refuses_an_ineligible_enrollment_without_calling_the_generator(
    settings,
):
    called = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_GENERATOR": lambda enrollment, certificate: called.append(1),
    }
    _course, cohort, _unit = eligibility_course_and_cohort()
    _user, enrollment = enrollment_for(cohort, email="refused@example.com")

    certificate, eligibility = request_certificate(enrollment)

    assert certificate is None
    assert eligibility.eligible is False
    assert called == []
    assert Certificate.objects.filter(enrollment=enrollment).count() == 0


def test_request_certificate_issues_via_the_configured_generator_when_eligible(settings):
    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_GENERATOR": (
            lambda enrollment, certificate: f"https://certs.example.com/{enrollment.id}.pdf"
        ),
    }
    course, cohort, unit = eligibility_course_and_cohort()
    _user, enrollment = enrollment_for(cohort, email="request@example.com")
    mark_completed(enrollment.user, unit, cohort=cohort)
    project = make_project(cohort)
    make_passed_submission(project, enrollment)

    certificate, eligibility = request_certificate(enrollment)

    assert eligibility.eligible is True
    assert certificate is not None
    assert certificate.url == f"https://certs.example.com/{enrollment.id}.pdf"
    enrollment.refresh_from_db()
    assert enrollment.certificate_url == certificate.url


def test_request_certificate_raises_when_no_generator_is_configured(settings):
    settings.COMMUNITY_BASE = {}
    course, cohort, unit = eligibility_course_and_cohort()
    _user, enrollment = enrollment_for(cohort, email="unconfigured@example.com")
    mark_completed(enrollment.user, unit, cohort=cohort)
    project = make_project(cohort)
    make_passed_submission(project, enrollment)

    with pytest.raises(ImproperlyConfigured):
        request_certificate(enrollment)
    assert Certificate.objects.filter(enrollment=enrollment).count() == 0


def test_request_certificate_reattaches_an_artifact_to_an_already_issued_certificate(settings):
    """Grandfathering recommendation from DataTalksClub/community-base#256: an eligible
    enrollment that already has a certificate is not refused as "already issued"."""

    settings.COMMUNITY_BASE = {
        "COURSEWORK_CERTIFICATE_GENERATOR": (
            lambda enrollment, certificate: "https://certs.example.com/regenerated.pdf"
        ),
    }
    course, cohort, unit = eligibility_course_and_cohort()
    _user, enrollment = enrollment_for(cohort, email="already-issued@example.com")
    mark_completed(enrollment.user, unit, cohort=cohort)
    project = make_project(cohort)
    make_passed_submission(project, enrollment)
    issue_certificate(enrollment, url="")  # grandfathered row, no artifact

    certificate, eligibility = request_certificate(enrollment)

    assert eligibility.eligible is True
    assert certificate.url == "https://certs.example.com/regenerated.pdf"
    assert Certificate.objects.filter(enrollment=enrollment).count() == 1


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
