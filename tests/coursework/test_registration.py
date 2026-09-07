import datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework.models import (
    CourseRegistration,
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
from tests.coursework.test_models import coursework_cohort, homework
from tests.coursework.test_projects import make_project
from tests.curriculum.test_models import make_cohort

pytestmark = pytest.mark.django_db


def make_campaign(slug="campaign", **values):
    values.setdefault("title", f"Campaign {slug}")
    return RegistrationCampaign.objects.create(slug=slug, **values)


def native_row(campaign, email, created_at=None, **values):
    row = CourseRegistration.objects.create(
        campaign=campaign,
        email=email,
        name=values.pop("name", email),
        country=values.pop("country", "Wonderland"),
        region=values.pop("region", "Nowhere"),
        role=values.pop("role", "other"),
        **values,
    )
    if created_at is not None:
        CourseRegistration.objects.filter(pk=row.pk).update(created_at=created_at)
        row.refresh_from_db()
    return row


def days_ago(days):
    return timezone.now() - datetime.timedelta(days=days)


def test_count_is_none_when_campaign_promotes_no_cohort():
    campaign = make_campaign()
    assert public_course_registration_count(campaign) is None


def test_count_is_baseline_plus_native_rows_for_current_cohort(db):
    cohort = coursework_cohort()
    campaign = make_campaign(
        current_cohort=cohort,
        registration_baseline_cohort=cohort,
        registration_baseline_count=120,
        registration_native_start_at=days_ago(1),
    )
    native_row(campaign, "old@example.com", created_at=days_ago(2))
    native_row(campaign, "one@example.com", created_at=days_ago(0))
    native_row(campaign, "two@example.com", created_at=days_ago(0))

    assert public_course_registration_count(campaign) == 122


def test_count_excludes_pre_native_rows_only_while_baseline_applies(db):
    cohort = coursework_cohort()
    other = make_cohort(cohort.course, slug="cw-2025", title="2025 cohort")
    campaign = make_campaign(
        current_cohort=cohort,
        registration_baseline_cohort=other,
        registration_baseline_count=50,
        registration_native_start_at=days_ago(1),
    )
    native_row(campaign, "old@example.com", created_at=days_ago(2))
    native_row(campaign, "new@example.com", created_at=days_ago(0))

    # The baseline names a different cohort, so neither the baseline nor its
    # boundary applies: every native row counts.
    assert public_course_registration_count(campaign) == 2


def test_baseline_does_not_carry_onto_the_next_edition(db):
    old = make_cohort(cohort_course := coursework_cohort().course, slug="cw-2025")
    cohort = make_cohort(cohort_course, slug="cw-2026", title="2026 cohort")
    campaign = make_campaign(
        current_cohort=old,
        registration_baseline_cohort=old,
        registration_baseline_count=120,
        registration_native_start_at=days_ago(1),
    )
    native_row(campaign, "carried@example.com", created_at=days_ago(0))

    campaign = stop_registration(campaign)
    campaign = open_new_cohort(campaign, cohort)
    native_row(campaign, "fresh@example.com")

    assert public_course_registration_count(campaign) == 1


def test_count_without_baseline_counts_all_native_rows(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    native_row(campaign, "one@example.com", created_at=days_ago(30))
    native_row(campaign, "two@example.com", created_at=days_ago(3))

    assert public_course_registration_count(campaign) == 2


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://courses.datatalks.club/register/ml-zoomcamp-2026/", "ml-zoomcamp-2026"),
        ("http://localhost/register/slug", "slug"),
        ("https://example.com/register/s", "s"),
    ],
)
def test_campaign_slug_accepted(url, slug):
    assert campaign_slug_in_registration_url(url) == slug


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com/courses/ml-zoomcamp-2026/",
        "https://example.com/register/-leading-dash/",
        "https://example.com/register/trailing-/",
        "https://example.com/register/Mixed-Case/",
        "not a url",
    ],
)
def test_campaign_slug_rejected(url):
    assert campaign_slug_in_registration_url(url) == ""


def test_active_campaign_for_cohort_returns_lowest_id_active_campaign(db):
    cohort = coursework_cohort()
    first = make_campaign(slug="first", current_cohort=cohort)
    make_campaign(slug="second", current_cohort=cohort)

    assert active_campaign_for_cohort(cohort) == first


def test_active_campaign_for_cohort_returns_none_without_match(db):
    cohort = coursework_cohort()
    make_campaign(slug="inactive", current_cohort=cohort, is_active=False)
    make_campaign(slug="elsewhere", current_cohort=make_cohort(cohort.course, slug="other"))

    assert active_campaign_for_cohort(cohort) is None


def test_next_edition_campaign_resolves_from_registration_url(db):
    cohort = coursework_cohort()
    cohort.registration_url = "https://courses.datatalks.club/register/next-up/"
    cohort.save()
    campaign = make_campaign(slug="next-up", current_cohort=make_cohort(cohort.course, slug="n"))

    assert next_edition_campaign_for_cohort(cohort) == campaign


def test_next_edition_campaign_excludes_campaign_promoting_this_cohort(db):
    cohort = coursework_cohort()
    cohort.registration_url = "https://courses.datatalks.club/register/self/"
    cohort.save()
    make_campaign(slug="self", current_cohort=cohort)

    assert next_edition_campaign_for_cohort(cohort) is None


def test_next_edition_campaign_ignores_inactive_and_unknown_slugs(db):
    cohort = coursework_cohort()
    cohort.registration_url = "https://courses.datatalks.club/register/ghost/"
    cohort.save()
    make_campaign(slug="ghost", current_cohort=None, is_active=False)

    assert next_edition_campaign_for_cohort(cohort) is None

    cohort.registration_url = "https://courses.datatalks.club/register/missing/"
    cohort.save()

    assert next_edition_campaign_for_cohort(cohort) is None


def test_next_edition_campaign_requires_a_campaign_url(db):
    cohort = coursework_cohort()

    assert next_edition_campaign_for_cohort(cohort) is None

    cohort.registration_url = "https://courses.datatalks.club/courses/some-course/"
    cohort.save()

    assert next_edition_campaign_for_cohort(cohort) is None


def test_family_registration_prefers_newest_edition_with_promoting_campaign(db):
    course = coursework_cohort().course
    older = make_cohort(course, slug="cw-2025", start_date=datetime.date(2025, 1, 1))
    newer = make_cohort(course, slug="cw-2026", start_date=datetime.date(2026, 1, 1))
    campaign = make_campaign(slug="current", current_cohort=older)

    registration = family_registration(course)

    assert registration == FamilyRegistration(campaign=campaign, cohort=older)
    assert newer.slug == "cw-2026"


def test_family_registration_breaks_start_date_ties_by_newest_row(db):
    course = coursework_cohort().course
    first = make_cohort(course, slug="tie-a", start_date=datetime.date(2026, 1, 1))
    second = make_cohort(course, slug="tie-b", start_date=datetime.date(2026, 1, 1))
    campaign = make_campaign(slug="tie-campaign", current_cohort=second)

    registration = family_registration(course)

    assert registration == FamilyRegistration(campaign=campaign, cohort=second)
    assert first.pk < second.pk


def test_family_registration_falls_back_to_next_edition_campaign(db):
    course = coursework_cohort().course
    closed = make_cohort(course, slug="cw-2025", start_date=datetime.date(2025, 1, 1))
    closed.registration_url = "https://courses.datatalks.club/register/waiting/"
    closed.save()
    campaign = make_campaign(slug="waiting", current_cohort=None)

    registration = family_registration(course)

    assert registration == FamilyRegistration(campaign=campaign, cohort=None)
    assert bool(registration) is True
    assert registration.cohort is None


def test_family_registration_skips_invisible_editions(db):
    course = coursework_cohort().course
    hidden = make_cohort(course, slug="cw-hidden", start_date=datetime.date(2026, 1, 1))
    hidden.visible = False
    hidden.save()
    make_campaign(slug="hidden-campaign", current_cohort=hidden)

    assert family_registration(course) == FamilyRegistration()


def test_family_registration_without_any_campaign_is_falsy(db):
    course = coursework_cohort().course

    registration = family_registration(course)

    assert registration == FamilyRegistration()
    assert not registration


def test_campaign_course_is_open_needs_content(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)

    assert campaign_course_is_open(campaign) is False

    homework(cohort)

    assert campaign_course_is_open(campaign) is True


def test_campaign_course_is_open_counts_projects_and_none_without_cohort(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    make_project(cohort)

    assert campaign_course_is_open(campaign) is True

    stopped = stop_registration(campaign)

    assert campaign_course_is_open(stopped) is False


def test_stop_registration_clears_cohort_and_fires_campaign_changed(db, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)

    stopped = stop_registration(campaign)

    assert stopped.current_cohort is None
    assert len(seen) == 1
    assert seen[0]["action"] == "registration_stopped"
    assert seen[0]["previous_cohort"] == cohort
    assert seen[0]["current_cohort"] is None


def test_stop_registration_fails_closed_without_an_open_cohort(db, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    campaign = make_campaign()

    with pytest.raises(RegistrationCampaignStateError):
        stop_registration(campaign)

    campaign.refresh_from_db()
    assert campaign.current_cohort is None
    assert seen == []


def test_open_new_cohort_sets_cohort_and_fires_campaign_changed(db, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    cohort = coursework_cohort()
    campaign = make_campaign()

    opened = open_new_cohort(campaign, cohort)

    assert opened.current_cohort == cohort
    assert len(seen) == 1
    assert seen[0]["action"] == "cohort_opened"
    assert seen[0]["previous_cohort"] is None
    assert seen[0]["current_cohort"] == cohort


def test_open_new_cohort_refuses_to_repoint_an_open_campaign(db, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_CAMPAIGN_CHANGED": lambda **event: seen.append(event),
    }
    current = coursework_cohort()
    successor = make_cohort(current.course, slug="cw-next")
    campaign = make_campaign(current_cohort=current)

    with pytest.raises(RegistrationCampaignStateError):
        open_new_cohort(campaign, successor)

    campaign.refresh_from_db()
    assert campaign.current_cohort == current
    assert seen == []


def test_open_new_cohort_requires_a_saved_cohort(db):
    campaign = make_campaign()

    with pytest.raises(RegistrationCampaignStateError):
        open_new_cohort(campaign, None)

    with pytest.raises(RegistrationCampaignStateError):
        open_new_cohort(campaign, CohortNotSaved())


class CohortNotSaved:
    """A cohort-shaped object with no database row."""

    pk = None


def test_create_course_registration_normalizes_and_attaches_user(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    user = User.objects.create_user(email="account@example.com")

    registration = create_course_registration(
        campaign,
        email="  Learner@Example.COM ",
        name="Learner",
        country="Wonderland",
        region="Nowhere",
        role="data_engineer",
        company_name="ACME",
        comment="hello",
        accepted_newsletter=True,
        user=user,
    )

    assert registration.email_normalized == "learner@example.com"
    assert registration.campaign == campaign
    assert registration.cohort == cohort
    assert registration.user == user
    assert registration.accepted_newsletter is True


def test_create_course_registration_rejects_duplicate_normalized_email(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    native_row(campaign, "taken@example.com")

    with pytest.raises(ValidationError):
        create_course_registration(
            campaign,
            email="Taken@Example.com",
            name="Again",
            country="Wonderland",
            region="Nowhere",
            role="other",
        )

    assert CourseRegistration.objects.filter(campaign=campaign).count() == 1


def test_create_course_registration_allows_same_email_on_other_campaign(db):
    cohort = coursework_cohort()
    first = make_campaign(slug="first", current_cohort=cohort)
    second = make_campaign(slug="second", current_cohort=cohort)
    create_course_registration(
        first,
        email="learner@example.com",
        name="Learner",
        country="Wonderland",
        region="Nowhere",
        role="other",
    )

    registration = create_course_registration(
        second,
        email="learner@example.com",
        name="Learner",
        country="Wonderland",
        region="Nowhere",
        role="other",
    )

    assert registration.campaign == second


def test_create_course_registration_snapshots_or_overrides_cohort(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)

    snapshotted = create_course_registration(
        campaign,
        email="snapshot@example.com",
        name="Snapshot",
        country="Wonderland",
        region="Nowhere",
        role="other",
    )
    override = create_course_registration(
        campaign,
        email="override@example.com",
        name="Override",
        country="Wonderland",
        region="Nowhere",
        role="other",
        cohort=coursework_cohort(slug="cw-past"),
    )

    assert snapshotted.cohort == cohort
    assert override.cohort.slug == "cw-past"


def test_create_course_registration_without_current_cohort_keeps_cohort_empty(db):
    campaign = make_campaign()

    registration = create_course_registration(
        campaign,
        email="waitlisted@example.com",
        name="Waitlist",
        country="Wonderland",
        region="Nowhere",
        role="other",
    )

    assert registration.cohort is None


def test_create_course_registration_fires_submitted_hook_after_save(db, settings):
    seen = []
    settings.COMMUNITY_BASE = {
        "COURSEWORK_REGISTRATION_SUBMITTED": lambda **event: seen.append(event),
    }
    campaign = make_campaign(current_cohort=coursework_cohort())

    registration = create_course_registration(
        campaign,
        email="hooked@example.com",
        name="Hooked",
        country="Wonderland",
        region="Nowhere",
        role="other",
    )

    assert seen == [{"registration": registration}]


def test_existing_course_registration_matches_by_user(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    user = User.objects.create_user(email="member@example.com")
    linked = native_row(campaign, "unrelated@example.com", user=user)

    assert existing_course_registration(campaign, user) == linked


def test_existing_course_registration_matches_by_normalized_email(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    user = User.objects.create_user(email="Member@Example.com")
    by_email = native_row(campaign, "member@example.com")

    assert existing_course_registration(campaign, user) == by_email


def test_existing_course_registration_is_scoped_to_the_campaign(db):
    cohort = coursework_cohort()
    first = make_campaign(slug="first", current_cohort=cohort)
    second = make_campaign(slug="second", current_cohort=cohort)
    user = User.objects.create_user(email="member@example.com")
    native_row(first, "member@example.com", user=user)

    assert existing_course_registration(first, user) is not None
    assert existing_course_registration(second, user) is None


def test_existing_course_registration_ignores_anonymous_visitors(db):
    cohort = coursework_cohort()
    campaign = make_campaign(current_cohort=cohort)
    native_row(campaign, "member@example.com")

    assert existing_course_registration(campaign, None) is None
