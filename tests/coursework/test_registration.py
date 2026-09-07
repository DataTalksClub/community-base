"""Registration campaign semantics ported from the DTC donor tests.

Covers spec 04 count semantics (``public_course_registration_count``), campaign
selection and bindings, lifecycle transitions (with the package hooks replacing the
donor's audit events), ``campaign_course_is_open`` and the registration creation
service.
"""

import datetime
from datetime import UTC, date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from community_base.accounts.models import User
from community_base.coursework import registration
from community_base.coursework.hooks import hooks as coursework_hooks
from community_base.coursework.models import (
    CourseRegistration,
    Project,
    RegistrationCampaign,
)
from community_base.curriculum.models import Cohort
from tests.coursework.test_models import coursework_cohort, coursework_course, homework
from tests.curriculum.test_models import make_cohort

pytestmark = pytest.mark.django_db

REGISTER_URL = "https://courses.datatalks.club/register/de-zoomcamp/"
NATIVE_START = datetime.datetime(2026, 2, 1, tzinfo=UTC)


def make_campaign(slug="de-zoomcamp", title="Data Engineering Zoomcamp", **values):
    return RegistrationCampaign.objects.create(slug=slug, title=title, **values)


def make_registration(campaign, cohort=None, email="learner@example.com", **values):
    values.setdefault("name", "Learner")
    values.setdefault("country", "Germany")
    values.setdefault("region", "Europe")
    values.setdefault("role", CourseRegistration.Role.DATA_ENGINEER)
    if cohort is not None:
        values["cohort"] = cohort
    return CourseRegistration.objects.create(campaign=campaign, email=email, **values)


def set_baseline(campaign, cohort, count=5, native_start_at=NATIVE_START):
    campaign.registration_baseline_cohort = cohort
    campaign.registration_baseline_count = count
    campaign.registration_native_start_at = native_start_at
    campaign.save(
        update_fields=(
            "registration_baseline_cohort",
            "registration_baseline_count",
            "registration_native_start_at",
            "updated_at",
        )
    )


class TestPublicCourseRegistrationCount:
    def test_no_current_cohort_returns_none(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        campaign.current_cohort = None
        campaign.save(update_fields=("current_cohort", "updated_at"))

        assert registration.public_course_registration_count(campaign) is None

    def test_plain_count_of_native_rows_for_current_cohort(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)

        assert registration.public_course_registration_count(campaign).count == 0

        make_registration(campaign, cohort=cohort, email="one@example.com")
        make_registration(campaign, cohort=cohort, email="two@example.com")

        assert registration.public_course_registration_count(campaign).count == 2

    def test_count_is_specific_to_campaign_and_cohort(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        make_registration(campaign, cohort=cohort, email="one@example.com")
        other_cohort = coursework_cohort(slug="other")
        other_campaign = make_campaign(
            slug="other-campaign", title="Other campaign", current_cohort=other_cohort
        )
        make_registration(other_campaign, cohort=other_cohort, email="two@example.com")
        make_registration(other_campaign, cohort=other_cohort, email="three@example.com")

        assert registration.public_course_registration_count(campaign).count == 1
        assert registration.public_course_registration_count(other_campaign).count == 2

    def test_baseline_plus_native_combines_once(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        set_baseline(campaign, cohort, count=5)
        native_one = make_registration(campaign, cohort=cohort, email="native-one@example.com")
        native_two = make_registration(campaign, cohort=cohort, email="native-two@example.com")
        CourseRegistration.objects.filter(pk=native_one.pk).update(
            created_at=NATIVE_START + timedelta(days=1)
        )
        CourseRegistration.objects.filter(pk=native_two.pk).update(
            created_at=NATIVE_START + timedelta(days=2)
        )

        assert registration.public_course_registration_count(campaign).count == 7

    def test_rows_before_the_native_cutover_are_not_double_counted(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        set_baseline(campaign, cohort, count=5)
        # A row that was itself part of what the recorded baseline already
        # covers (for example a backfilled historical row) must not be
        # counted a second time.
        pre_cutover = make_registration(campaign, cohort=cohort, email="pre-cutover@example.com")
        CourseRegistration.objects.filter(pk=pre_cutover.pk).update(
            created_at=NATIVE_START - timedelta(days=1)
        )

        assert registration.public_course_registration_count(campaign).count == 5

    def test_rows_created_exactly_at_the_native_boundary_are_counted(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        set_baseline(campaign, cohort, count=5)
        boundary_row = make_registration(campaign, cohort=cohort, email="boundary@example.com")
        CourseRegistration.objects.filter(pk=boundary_row.pk).update(created_at=NATIVE_START)

        assert registration.public_course_registration_count(campaign).count == 6

    def test_baseline_does_not_carry_onto_a_rotated_cohort(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        set_baseline(campaign, cohort, count=5)
        next_cohort = coursework_cohort(slug="next")
        campaign.current_cohort = next_cohort
        campaign.save(update_fields=("current_cohort", "updated_at"))
        make_registration(campaign, cohort=next_cohort, email="next-edition@example.com")

        # Only the new edition's own native row counts -- the old baseline
        # was recorded for the previous cohort and stays with it.
        assert registration.public_course_registration_count(campaign).count == 1


class TestCampaignSlugReading:
    def test_reads_the_campaign_slug_a_cmp_registration_url_names(self):
        assert registration.campaign_slug_in_registration_url(REGISTER_URL) == "de-zoomcamp"
        assert (
            registration.campaign_slug_in_registration_url(
                "http://example.test/register/ml-zoomcamp"
            )
            == "ml-zoomcamp"
        )

    def test_reads_nothing_from_a_url_that_is_not_a_campaign_page(self):
        for value in (
            "",
            "https://courses.datatalks.club/de-zoomcamp-2026/",
            "https://example.test/register/",
            "https://example.test/register/a/b/",
            "not a url",
        ):
            assert registration.campaign_slug_in_registration_url(value) == ""


class TestCohortCampaignSelection:
    def test_a_campaign_promoting_this_edition_is_the_edition_campaign(self):
        cohort = coursework_cohort()
        cohort.registration_url = REGISTER_URL
        cohort.save(update_fields=["registration_url"])
        campaign = make_campaign(current_cohort=cohort)

        assert registration.active_campaign_for_cohort(cohort) == campaign
        assert registration.next_edition_campaign_for_cohort(cohort) is None

    def test_a_closed_edition_offers_the_campaign_its_own_url_names(self):
        cohort = coursework_cohort()
        cohort.registration_url = REGISTER_URL
        cohort.save(update_fields=["registration_url"])
        campaign = make_campaign()

        assert registration.active_campaign_for_cohort(cohort) is None
        assert registration.next_edition_campaign_for_cohort(cohort) == campaign

    def test_selection_picks_the_lowest_id_active_campaign(self):
        cohort = coursework_cohort()
        first = make_campaign(slug="first-campaign", title="First", current_cohort=cohort)
        make_campaign(slug="second-campaign", title="Second", current_cohort=cohort)

        assert registration.active_campaign_for_cohort(cohort) == first

    def test_an_inactive_campaign_is_never_offered(self):
        cohort = coursework_cohort()
        cohort.registration_url = REGISTER_URL
        cohort.save(update_fields=["registration_url"])
        make_campaign(is_active=False)

        assert registration.next_edition_campaign_for_cohort(cohort) is None
        assert registration.active_campaign_for_cohort(cohort) is None

    def test_a_registration_url_naming_no_local_campaign_offers_nothing(self):
        cohort = coursework_cohort()
        cohort.registration_url = REGISTER_URL
        cohort.save(update_fields=["registration_url"])

        assert registration.next_edition_campaign_for_cohort(cohort) is None

    def test_a_url_that_is_not_a_campaign_path_offers_nothing(self):
        cohort = coursework_cohort()
        cohort.registration_url = "https://courses.datatalks.club/de-zoomcamp-2026/"
        cohort.save(update_fields=["registration_url"])
        make_campaign()

        assert registration.next_edition_campaign_for_cohort(cohort) is None


class TestFamilyRegistration:
    def test_an_open_edition_is_named_because_naming_it_is_honest(self):
        course = coursework_course()
        make_cohort(course, slug="2025", title="2025 cohort", start_date=date(2025, 1, 15))
        current = make_cohort(
            course, slug="2026", title="2026 cohort", start_date=date(2026, 1, 15)
        )
        campaign = make_campaign(
            slug="ai-dev-tools",
            title="AI Dev Tools Zoomcamp",
            current_cohort=current,
        )

        result = registration.family_registration(course)

        assert bool(result) is True
        assert result.campaign == campaign
        assert result.cohort == current

    def test_a_family_whose_editions_have_all_closed_names_no_edition(self):
        course = coursework_course()
        cohort = make_cohort(course, slug="2026", title="2026 cohort", start_date=date(2026, 1, 15))
        cohort.registration_url = REGISTER_URL
        cohort.save(update_fields=["registration_url"])
        campaign = make_campaign()

        result = registration.family_registration(course)

        assert result.campaign == campaign
        assert result.cohort is None

    def test_a_family_with_no_successor_and_no_campaign_offers_nothing(self):
        course = coursework_course()
        make_cohort(course, slug="2024", title="2024 cohort", start_date=date(2024, 1, 15))
        make_cohort(course, slug="2025", title="2025 cohort", start_date=date(2025, 1, 15))

        result = registration.family_registration(course)

        assert bool(result) is False
        assert result.campaign is None

    def test_newest_edition_is_chosen_by_start_date_not_by_id(self):
        # The donor orders editions by ("year", id); the package has no year
        # column, so the newest start_date wins even when an older edition has
        # the higher id.
        course = coursework_course()
        newest = make_cohort(course, slug="2026", title="2026 cohort", start_date=date(2026, 1, 15))
        make_cohort(course, slug="2025", title="2025 cohort", start_date=date(2025, 1, 15))
        campaign = make_campaign(current_cohort=newest)

        result = registration.family_registration(course)

        assert result.campaign == campaign
        assert result.cohort == newest

    def test_editions_without_a_start_date_sort_last(self):
        course = coursework_course()
        make_cohort(course, slug="self-paced", title="Self-paced", start_date=None)
        edition = make_cohort(
            course, slug="2025", title="2025 cohort", start_date=date(2025, 1, 15)
        )
        make_campaign(current_cohort=edition)

        result = registration.family_registration(course)

        assert result.cohort == edition

    def test_the_next_edition_offer_follows_the_newest_closed_edition(self):
        course = coursework_course()
        newer = make_cohort(course, slug="2026", title="2026 cohort", start_date=date(2026, 1, 15))
        newer.registration_url = "https://courses.datatalks.club/register/campaign-b/"
        newer.save(update_fields=["registration_url"])
        older = make_cohort(course, slug="2025", title="2025 cohort", start_date=date(2025, 1, 15))
        older.registration_url = "https://courses.datatalks.club/register/campaign-a/"
        older.save(update_fields=["registration_url"])
        campaign_b = make_campaign(slug="campaign-b", title="Campaign B")
        make_campaign(slug="campaign-a", title="Campaign A")

        result = registration.family_registration(course)

        assert result.campaign == campaign_b
        assert result.cohort is None

    def test_invisible_editions_are_never_offered(self):
        course = coursework_course()
        hidden = make_cohort(
            course,
            slug="hidden",
            title="Hidden cohort",
            start_date=date(2026, 1, 15),
            visible=False,
        )
        make_campaign(current_cohort=hidden)

        result = registration.family_registration(course)

        assert bool(result) is False


class TestRegistrationCampaignLifecycle:
    def test_stop_registration_clears_current_cohort(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)

        updated = registration.stop_registration(campaign)

        assert updated.current_cohort is None
        campaign.refresh_from_db()
        assert campaign.current_cohort is None

    def test_stop_registration_fires_the_stopped_hook(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            coursework_hooks, "registration_campaign_stopped", lambda **event: seen.append(event)
        )
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)

        updated = registration.stop_registration(campaign)

        assert len(seen) == 1
        assert seen[0]["campaign"].pk == campaign.pk
        assert seen[0]["campaign"].current_cohort is None
        assert seen[0]["previous_cohort"] == cohort
        assert updated.pk == campaign.pk

    def test_stop_registration_fails_closed_when_already_stopped(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            coursework_hooks, "registration_campaign_stopped", lambda **event: seen.append(event)
        )
        campaign = make_campaign()
        campaign.current_cohort = None
        campaign.save(update_fields=("current_cohort", "updated_at"))

        with pytest.raises(
            registration.RegistrationCampaignStateError,
            match="This campaign has no open cohort to stop registration for.",
        ):
            registration.stop_registration(campaign)

        assert campaign.current_cohort is None
        assert seen == []

    def test_state_error_is_a_value_error(self):
        assert issubclass(registration.RegistrationCampaignStateError, ValueError)

    def test_open_new_cohort_sets_current_cohort(self):
        cohort = coursework_cohort()
        next_cohort = coursework_cohort(slug="next")
        campaign = make_campaign(current_cohort=cohort)
        campaign.current_cohort = None
        campaign.save(update_fields=("current_cohort", "updated_at"))

        updated = registration.open_new_cohort(campaign, next_cohort)

        assert updated.current_cohort == next_cohort
        campaign.refresh_from_db()
        assert campaign.current_cohort == next_cohort

    def test_open_new_cohort_fires_the_cohort_opened_hook(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            coursework_hooks, "registration_cohort_opened", lambda **event: seen.append(event)
        )
        next_cohort = coursework_cohort(slug="next")
        campaign = make_campaign()
        campaign.current_cohort = None
        campaign.save(update_fields=("current_cohort", "updated_at"))

        updated = registration.open_new_cohort(campaign, next_cohort)

        assert len(seen) == 1
        assert seen[0]["campaign"].pk == updated.pk
        assert seen[0]["cohort"] == next_cohort

    def test_open_new_cohort_guard_rejects_a_still_open_campaign(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            coursework_hooks, "registration_cohort_opened", lambda **event: seen.append(event)
        )
        cohort = coursework_cohort()
        next_cohort = coursework_cohort(slug="next")
        campaign = make_campaign(current_cohort=cohort)

        with pytest.raises(
            registration.RegistrationCampaignStateError,
            match="Stop registration for the current cohort before opening a new one.",
        ):
            registration.open_new_cohort(campaign, next_cohort)

        campaign.refresh_from_db()
        assert campaign.current_cohort == cohort
        assert seen == []

    def test_stop_then_open_round_trip(self):
        cohort = coursework_cohort()
        next_cohort = coursework_cohort(slug="next")
        campaign = make_campaign(current_cohort=cohort)

        registration.stop_registration(campaign)
        updated = registration.open_new_cohort(campaign, next_cohort)

        assert updated.current_cohort == next_cohort

    def test_open_new_cohort_requires_a_cohort_instance(self):
        campaign = make_campaign()
        campaign.current_cohort = None
        campaign.save(update_fields=("current_cohort", "updated_at"))

        with pytest.raises(
            registration.RegistrationCampaignStateError,
            match="Choose an existing cohort to open registration for.",
        ):
            registration.open_new_cohort(campaign, Cohort())

        campaign.refresh_from_db()
        assert campaign.current_cohort is None


class TestCampaignCourseIsOpen:
    def test_openness_requires_a_current_cohort(self):
        campaign = make_campaign()

        assert registration.campaign_course_is_open(campaign) is False

    def test_openness_is_derived_from_cohort_coursework(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)

        assert registration.campaign_course_is_open(campaign) is False

        homework(cohort)

        assert registration.campaign_course_is_open(campaign) is True

    def test_a_project_also_opens_the_course(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)
        Project.objects.create(
            cohort=cohort,
            slug="final",
            title="Final project",
            submission_due_date=timezone.now(),
            peer_review_due_date=timezone.now(),
        )

        assert registration.campaign_course_is_open(campaign) is True


class TestCreateCourseRegistration:
    def make_kwargs(self, **overrides):
        kwargs = {
            "email": "  Learner@Example.COM ",
            "name": "Learner",
            "country": "Germany",
            "role": CourseRegistration.Role.DATA_ENGINEER,
        }
        kwargs.update(overrides)
        return kwargs

    def test_snapshots_the_current_cohort_and_normalizes_the_email(self):
        cohort = coursework_cohort()
        campaign = make_campaign(current_cohort=cohort)

        row = registration.create_course_registration(
            campaign,
            **self.make_kwargs(company_name="Acme Data", comment="hi", accepted_newsletter=False),
        )

        assert row.cohort_id == cohort.id  # defaulting from the campaign
        assert row.email == "learner@example.com"
        assert row.email_normalized == "learner@example.com"
        assert row.name == "Learner"
        assert row.country == "Germany"
        assert row.region == ""
        assert row.company_name == "Acme Data"
        assert row.comment == "hi"
        assert row.accepted_newsletter is False
        assert row.user is None

    def test_rejects_a_duplicate_per_campaign_with_the_donor_message(self):
        campaign = make_campaign()
        registration.create_course_registration(campaign, **self.make_kwargs())

        with pytest.raises(ValidationError) as excinfo:
            registration.create_course_registration(
                campaign, **self.make_kwargs(email="Learner@Example.com")
            )

        assert excinfo.value.messages == ["You have already registered for this course."]
        assert CourseRegistration.objects.count() == 1

    def test_the_same_email_can_register_through_a_different_campaign(self):
        cohort = coursework_cohort()
        first = make_campaign(slug="first-campaign", title="First", current_cohort=cohort)
        second = make_campaign(slug="second-campaign", title="Second", current_cohort=cohort)
        registration.create_course_registration(first, **self.make_kwargs())

        row = registration.create_course_registration(second, **self.make_kwargs())

        assert row.campaign == second

    def test_region_resolver_derives_the_region_from_the_country(self):
        campaign = make_campaign()
        seen_countries = []

        def resolver(country):
            seen_countries.append(country)
            return "Europe"

        row = registration.create_course_registration(
            campaign, **self.make_kwargs(region_resolver=resolver)
        )

        assert seen_countries == ["Germany"]
        assert row.region == "Europe"

    def test_without_a_resolver_the_given_region_is_kept(self):
        campaign = make_campaign()

        row = registration.create_course_registration(campaign, **self.make_kwargs(region="Europe"))

        assert row.region == "Europe"

    def test_the_user_is_stored_and_no_profile_is_touched(self):
        campaign = make_campaign()
        user = User.objects.create_user(email="member@example.com")

        row = registration.create_course_registration(
            campaign, **self.make_kwargs(email="member@example.com", user=user)
        )

        assert row.user == user
        user.refresh_from_db()
        assert user.first_name == ""

    def test_fires_the_registration_created_hook(self, monkeypatch):
        seen = []
        monkeypatch.setattr(
            coursework_hooks, "registration_created", lambda **event: seen.append(event)
        )
        campaign = make_campaign()

        row = registration.create_course_registration(campaign, **self.make_kwargs())

        assert seen == [{"registration": row}]
