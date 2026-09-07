import datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    CourseRegistration,
    Project,
    RegistrationCampaign,
)
from community_base.coursework.registration import (
    FamilyRegistration,
    RegistrationCampaignStateError,
    active_campaign_for_cohort,
    campaign_course_is_open,
    campaign_slug_in_registration_url,
    create_course_registration,
    existing_course_registration,
    family_registration,
    next_edition_campaign_for_cohort,
    open_new_cohort,
    public_course_registration_count,
    stop_registration,
)
from community_base.curriculum.models import Cohort
from tests.coursework.test_models import coursework_cohort, coursework_course, homework

pytestmark = pytest.mark.django_db

REGISTER_URL = "https://courses.datatalks.club/register/{slug}/"


def make_campaign(slug="de", **values):
    values.setdefault("title", f"Campaign {slug}")
    return RegistrationCampaign.objects.create(slug=slug, **values)


def make_registration(campaign, email="learner@example.com", **values):
    values.setdefault("name", "Learner")
    values.setdefault("country", "DE")
    values.setdefault("region", "EU")
    values.setdefault("role", CourseRegistration.Role.DATA_ENGINEER)
    return CourseRegistration.objects.create(campaign=campaign, email=email, **values)


def make_project(cohort):
    return Project.objects.create(
        cohort=cohort,
        slug="final",
        title="Final project",
        submission_due_date=timezone.now(),
        peer_review_due_date=timezone.now(),
    )


def test_count_is_none_when_campaign_promotes_no_cohort():
    campaign = make_campaign(slug="idle")

    assert public_course_registration_count(campaign) is None


def test_count_is_baseline_plus_native_rows_for_current_cohort():
    cohort = coursework_cohort()
    older = coursework_cohort(slug="cw-older")
    campaign = make_campaign(
        slug="counted",
        current_cohort=cohort,
        registration_baseline_cohort=cohort,
        registration_baseline_count=120,
    )
    make_registration(campaign, "a@example.com", cohort=cohort)
    make_registration(campaign, "b@example.com", cohort=older)

    assert public_course_registration_count(campaign) == 121


def test_count_excludes_pre_native_rows_only_while_baseline_applies():
    cohort = coursework_cohort()
    campaign = make_campaign(
        slug="backfilled",
        current_cohort=cohort,
        registration_baseline_cohort=cohort,
        registration_baseline_count=50,
        registration_native_start_at=timezone.now(),
    )
    imported = make_registration(campaign, "imported@example.com")
    native = make_registration(campaign, "native@example.com")
    CourseRegistration.objects.filter(pk=imported.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=1)
    )
    CourseRegistration.objects.filter(pk=native.pk).update(created_at=timezone.now())

    assert public_course_registration_count(campaign) == 51


def test_baseline_does_not_carry_onto_the_next_edition():
    previous = coursework_cohort(slug="cw-2025", start_date=datetime.date(2025, 1, 1))
    current = coursework_cohort(slug="cw-2026", start_date=datetime.date(2026, 1, 1))
    campaign = make_campaign(
        slug="rotated",
        current_cohort=current,
        registration_baseline_cohort=previous,
        registration_baseline_count=300,
        registration_native_start_at=timezone.now(),
    )
    make_registration(campaign, "next@example.com")

    assert public_course_registration_count(campaign) == 1


def test_count_without_baseline_counts_all_native_rows():
    cohort = coursework_cohort()
    campaign = make_campaign(
        slug="all-native",
        current_cohort=cohort,
        registration_native_start_at=timezone.now() - datetime.timedelta(days=30),
    )
    early = make_registration(campaign, "early@example.com")
    make_registration(campaign, "late@example.com")
    CourseRegistration.objects.filter(pk=early.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=60)
    )

    assert public_course_registration_count(campaign) == 2


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://courses.datatalks.club/register/de-zoomcamp-2025/", "de-zoomcamp-2025"),
        ("http://datatalks.club/register/ml-zoomcamp", "ml-zoomcamp"),
        ("https://datatalks.club/register/a", "a"),
        ("  https://datatalks.club/register/x/  ", "x"),
    ],
)
def test_campaign_slug_accepted(url, slug):
    assert campaign_slug_in_registration_url(url) == slug


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "ftp://datatalks.club/register/x/",
        "https://datatalks.club/courses/de-zoomcamp-2025/",
        "https://datatalks.club/register/",
        "https://datatalks.club/register/UPPER/",
        "https://datatalks.club/register/-leading/",
        "https://datatalks.club/register/trailing-/",
        "https://datatalks.club/register/two/slugs/",
    ],
)
def test_campaign_slug_rejected(url):
    assert campaign_slug_in_registration_url(url) == ""


def test_active_campaign_for_cohort_returns_lowest_id_active_campaign():
    cohort = coursework_cohort()
    first = make_campaign(slug="first", current_cohort=cohort)
    make_campaign(slug="second", current_cohort=cohort)
    make_campaign(slug="inactive", current_cohort=cohort, is_active=False)

    assert active_campaign_for_cohort(cohort) == first


def test_active_campaign_for_cohort_returns_none_without_match():
    cohort = coursework_cohort()
    make_campaign(slug="idle")

    assert active_campaign_for_cohort(cohort) is None


def test_next_edition_campaign_resolves_from_registration_url():
    cohort = coursework_cohort(registration_url=REGISTER_URL.format(slug="de-2026"))
    current = coursework_cohort(slug="cw-2026")
    campaign = make_campaign(slug="de-2026", current_cohort=current)

    assert next_edition_campaign_for_cohort(cohort) == campaign


def test_next_edition_campaign_excludes_campaign_promoting_this_cohort():
    cohort = coursework_cohort(registration_url=REGISTER_URL.format(slug="mine"))
    make_campaign(slug="mine", current_cohort=cohort)

    assert next_edition_campaign_for_cohort(cohort) is None


def test_next_edition_campaign_ignores_inactive_and_unknown_slugs():
    inactive_cohort = coursework_cohort(
        slug="cw-inactive", registration_url=REGISTER_URL.format(slug="inactive")
    )
    unknown_cohort = coursework_cohort(
        slug="cw-unknown", registration_url=REGISTER_URL.format(slug="missing")
    )
    make_campaign(slug="inactive", is_active=False)

    assert next_edition_campaign_for_cohort(inactive_cohort) is None
    assert next_edition_campaign_for_cohort(unknown_cohort) is None


def test_next_edition_campaign_requires_a_campaign_url():
    cohort = coursework_cohort(registration_url="https://datatalks.club/courses/de/")
    make_campaign(slug="de")

    assert next_edition_campaign_for_cohort(cohort) is None


def test_family_registration_prefers_newest_edition_with_promoting_campaign():
    old = coursework_cohort(slug="fam-2024", start_date=datetime.date(2024, 1, 1))
    newest = coursework_cohort(slug="fam-2026", start_date=datetime.date(2026, 1, 1))
    newest_campaign = make_campaign(slug="fam-2026", current_cohort=newest)
    make_campaign(slug="fam-2024", current_cohort=old)

    result = family_registration(old.course)

    assert result.campaign == newest_campaign
    assert result.cohort == newest


def test_family_registration_breaks_start_date_ties_by_newest_row():
    first = coursework_cohort(slug="tie-a", start_date=datetime.date(2026, 1, 1))
    second = coursework_cohort(slug="tie-b", start_date=datetime.date(2026, 1, 1))
    campaign = make_campaign(slug="tie-b", current_cohort=second)

    result = family_registration(first.course)

    assert second.pk > first.pk
    assert result.campaign == campaign
    assert result.cohort == second


def test_family_registration_falls_back_to_next_edition_campaign():
    closed = coursework_cohort(
        slug="fam-closed",
        start_date=datetime.date(2024, 1, 1),
        registration_url=REGISTER_URL.format(slug="fam-next"),
    )
    campaign = make_campaign(slug="fam-next")

    result = family_registration(closed.course)

    assert result.campaign == campaign
    assert result.cohort is None
    assert bool(result) is True


def test_family_registration_skips_invisible_editions():
    hidden = coursework_cohort(slug="fam-hidden", visible=False)
    make_campaign(slug="fam-hidden", current_cohort=hidden)
    coursework_cohort(slug="fam-quiet")

    result = family_registration(hidden.course)

    assert not result


def test_family_registration_without_any_campaign_is_falsy():
    course = coursework_course()
    coursework_cohort(slug="fam-alone")

    result = family_registration(course)

    assert not result
    assert isinstance(result, FamilyRegistration)
    assert result.campaign is None
    assert result.cohort is None


def test_campaign_course_is_open_needs_homework_or_project():
    cohort = coursework_cohort()
    assert campaign_course_is_open(cohort) is False

    homework(cohort)
    assert campaign_course_is_open(cohort) is True


def test_campaign_course_is_open_counts_projects_too():
    cohort = coursework_cohort()
    make_project(cohort)

    assert campaign_course_is_open(cohort) is True


def test_stop_registration_locks_row_and_fires_campaign_changed(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    campaign = make_campaign(slug="live", current_cohort=cohort)

    returned = stop_registration(campaign)

    returned.refresh_from_db()
    assert returned.current_cohort is None
    assert RegistrationCampaign.objects.get(pk=campaign.pk).current_cohort is None
    assert len(seen) == 1
    assert seen[0]["campaign"].pk == campaign.pk
    assert seen[0]["action"] == "registration_stopped"
    assert seen[0]["previous_cohort"] == cohort
    assert seen[0]["current_cohort"] is None


def test_stop_registration_writes_only_the_cohort_fields():
    cohort = coursework_cohort()
    campaign = make_campaign(slug="live", current_cohort=cohort, title="Before")
    RegistrationCampaign.objects.filter(pk=campaign.pk).update(title="After")

    stop_registration(campaign)

    assert RegistrationCampaign.objects.get(pk=campaign.pk).title == "After"


def test_stop_registration_fails_closed_without_an_open_cohort(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    campaign = make_campaign(slug="already-stopped")

    with pytest.raises(RegistrationCampaignStateError):
        stop_registration(campaign)

    assert RegistrationCampaign.objects.get(pk=campaign.pk).current_cohort is None
    assert seen == []


def test_open_new_cohort_locks_row_and_fires_campaign_changed(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    campaign = make_campaign(slug="waiting")

    returned = open_new_cohort(campaign, cohort)

    returned.refresh_from_db()
    assert returned.current_cohort == cohort
    assert len(seen) == 1
    assert seen[0]["campaign"].pk == campaign.pk
    assert seen[0]["action"] == "cohort_opened"
    assert seen[0]["previous_cohort"] is None
    assert seen[0]["current_cohort"] == cohort


def test_open_new_cohort_refuses_to_repoint_an_open_campaign(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    next_cohort = coursework_cohort(slug="cw-next")
    campaign = make_campaign(slug="live", current_cohort=cohort)

    with pytest.raises(RegistrationCampaignStateError):
        open_new_cohort(campaign, next_cohort)

    assert RegistrationCampaign.objects.get(pk=campaign.pk).current_cohort == cohort
    assert seen == []


def test_open_new_cohort_requires_a_saved_cohort():
    campaign = make_campaign(slug="waiting")
    unsaved = Cohort(course=coursework_course(), slug="unsaved", title="Unsaved")

    with pytest.raises(RegistrationCampaignStateError):
        open_new_cohort(campaign, unsaved)


def test_create_course_registration_normalizes_and_attaches_user():
    cohort = coursework_cohort()
    campaign = make_campaign(slug="de", current_cohort=cohort)
    user = User.objects.create_user(email="member@example.com")

    registration = create_course_registration(
        campaign,
        email="  Learner@Example.COM ",
        name="Learner",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.DATA_ENGINEER,
        company_name="Acme",
        comment="Hello",
        accepted_newsletter=True,
        user=user,
    )

    assert registration.pk is not None
    assert registration.email_normalized == "learner@example.com"
    assert registration.user == user
    assert registration.company_name == "Acme"
    assert registration.comment == "Hello"
    assert registration.accepted_newsletter is True


def test_create_course_registration_rejects_duplicate_normalized_email():
    cohort = coursework_cohort()
    campaign = make_campaign(slug="de", current_cohort=cohort)
    create_course_registration(
        campaign,
        email="taken@example.com",
        name="First",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.OTHER,
    )

    with pytest.raises(ValidationError) as excinfo:
        create_course_registration(
            campaign,
            email=" Taken@Example.com ",
            name="Second",
            country="DE",
            region="EU",
            role=CourseRegistration.Role.OTHER,
        )

    assert "already registered" in str(excinfo.value)
    assert CourseRegistration.objects.filter(campaign=campaign).count() == 1


def test_create_course_registration_allows_same_email_on_other_campaign():
    cohort = coursework_cohort()
    first = make_campaign(slug="de", current_cohort=cohort)
    second = make_campaign(slug="ml", current_cohort=cohort)
    create_course_registration(
        first,
        email="taken@example.com",
        name="Learner",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.OTHER,
    )

    elsewhere = create_course_registration(
        second,
        email="taken@example.com",
        name="Learner",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.OTHER,
    )

    assert elsewhere.campaign == second


def test_create_course_registration_snapshots_or_overrides_cohort():
    promoted = coursework_cohort()
    other = coursework_cohort(slug="cw-other")
    campaign = make_campaign(slug="de", current_cohort=promoted)

    snapshot = create_course_registration(
        campaign,
        email="snapshotted@example.com",
        name="Learner",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.OTHER,
    )
    override = create_course_registration(
        campaign,
        email="overridden@example.com",
        name="Learner",
        country="DE",
        region="EU",
        role=CourseRegistration.Role.OTHER,
        cohort=other,
    )

    assert snapshot.cohort == promoted
    assert override.cohort == other


def test_create_course_registration_without_current_cohort_keeps_cohort_empty():
    campaign = make_campaign(slug="waiting")

    registration = create_course_registration(
        campaign,
        email="waiting@example.com",
        name="Learner",
        country="",
        region="",
        role=CourseRegistration.Role.OTHER,
    )

    assert registration.cohort is None


def test_create_course_registration_fires_submitted_hook_after_save(settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_SUBMITTED": lambda **event: seen.append(event),
    }
    campaign = make_campaign(slug="de")

    registration = create_course_registration(
        campaign,
        email="hook@example.com",
        name="Learner",
        country="",
        region="",
        role=CourseRegistration.Role.OTHER,
    )

    assert len(seen) == 1
    assert seen[0]["registration"].pk == registration.pk


def test_existing_course_registration_matches_user_or_normalized_email():
    cohort = coursework_cohort()
    campaign = make_campaign(slug="de", current_cohort=cohort)
    user = User.objects.create_user(email="member@example.com")
    by_user = make_registration(campaign, "other@example.com", user=user)
    make_registration(campaign, "Listed@Example.com")

    assert existing_course_registration(campaign, user, "mismatch@example.com") == by_user
    matched = existing_course_registration(campaign, None, " listed@example.com ")
    assert matched is not None
    assert matched.email_normalized == "listed@example.com"
    assert existing_course_registration(campaign, None, "nobody@example.com") is None


def test_existing_course_registration_is_scoped_to_the_campaign():
    cohort = coursework_cohort()
    campaign = make_campaign(slug="de", current_cohort=cohort)
    other = make_campaign(slug="ml", current_cohort=cohort)
    make_registration(other, "taken@example.com")

    assert existing_course_registration(campaign, None, "taken@example.com") is None
