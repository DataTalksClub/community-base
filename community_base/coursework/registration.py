"""Registration campaigns: cohort bindings, lifecycle and the public count.

Ported from DTC ``courses/services/registration_campaigns.py``,
``courses/services/registration_counts.py`` and the registration views (see
``docs/plan/evidence/c5.2d-registration-donors.md``).

A cohort reaches its campaign through one of two bindings:

* ``RegistrationCampaign.current_cohort`` -- the edition the campaign is promoting
  *now*. Clearing it means "future/none": the campaign waits for the next edition.
* ``Cohort.registration_url`` -- the campaign page the cohort's own row names, of the
  form ``https://courses.datatalks.club/register/<campaign-slug>/``. It outlives
  ``current_cohort``, so it is the binding that means "this course registers here".

Nothing is derived: a registration URL that is not a campaign path, or that names a
campaign this database does not hold, resolves to no registration at all.

Deviations from the donor, all recorded:

* The donor orders a course family's editions by ``("-year", "-id")``. The package
  ``Cohort`` has no ``year`` column, so :func:`family_registration` orders by
  ``start_date`` descending with nulls last, then ``-id`` -- newest edition first by
  the date the package actually carries.
* The donor's ``stop_registration``/``open_new_cohort`` record ``AuditEvent`` rows
  through the site audit kernel and take ``actor_ref``/``actor_id``/``context``
  parameters. The package has no audit kernel, so the services fire the
  ``registration_campaign_stopped``/``registration_cohort_opened`` hooks instead and
  take no actor parameters; audit rows stay a site concern that DTC wires through the
  hooks.
* The donor derives ``region`` from its ``courses/countries.txt`` catalog and
  validates the country against it in the form. The catalog is site content: the
  service accepts a ``region_resolver`` callable and DTC passes its catalog lookup
  (the same pattern as the C5.2c volunteer submission defaults).
* The donor form forces ``email`` to the account email for authenticated users and
  updates the user profile after save. Both are identity/account surfaces of the
  sign-in gate, not coursework: the caller passes the email to store (DTC's view
  passes the account email) and the package never touches user profiles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from community_base.coursework.hooks import hooks
from community_base.coursework.models import (
    CourseRegistration,
    Homework,
    Project,
    RegistrationCampaign,
)
from community_base.curriculum.models import Cohort, Course

__all__ = [
    "FamilyRegistration",
    "PublicCourseRegistrationCount",
    "RegistrationCampaignStateError",
    "active_campaign_for_cohort",
    "campaign_course_is_open",
    "campaign_slug_in_registration_url",
    "create_course_registration",
    "family_registration",
    "next_edition_campaign_for_cohort",
    "open_new_cohort",
    "public_course_registration_count",
    "stop_registration",
]

# CMP's own public registration path.  The host is deliberately unconstrained: what is
# read is the campaign slug the platform published, not the origin it published it on.
_CAMPAIGN_PATH = re.compile(
    r"^https?://[^/]+/register/(?P<slug>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/?$"
)


def campaign_slug_in_registration_url(registration_url: str) -> str:
    """Return the campaign slug a CMP registration URL names, or an empty string."""

    if not registration_url:
        return ""
    match = _CAMPAIGN_PATH.match(registration_url.strip())
    if match is None:
        return ""
    return match.group("slug")


def active_campaign_for_cohort(cohort: Cohort) -> RegistrationCampaign | None:
    """Return the active campaign promoting this exact edition, if there is one."""

    return (
        RegistrationCampaign.objects.filter(current_cohort=cohort, is_active=True)
        .order_by("id")
        .first()
    )


def next_edition_campaign_for_cohort(cohort: Cohort) -> RegistrationCampaign | None:
    """Return the campaign this cohort's course registers through, for a closed edition.

    Only meaningful when no campaign promotes this edition: it is the waiting list for
    whatever runs next.  A campaign that *is* promoting this edition is returned by
    :func:`active_campaign_for_cohort` instead, so this never duplicates it.
    """

    slug = campaign_slug_in_registration_url(cohort.registration_url)
    if not slug:
        return None
    campaign = RegistrationCampaign.objects.filter(slug=slug, is_active=True).first()
    if campaign is None or campaign.current_cohort_id == cohort.id:
        return None
    return campaign


@dataclass(frozen=True, slots=True)
class FamilyRegistration:
    """What a course family currently offers a visitor who wants to register.

    ``cohort`` is set only when a campaign is promoting that exact edition, which is the
    one case where naming an edition is honest.  A family whose editions have all closed
    keeps the campaign and drops the edition, so the page can say "the next edition"
    without naming a cohort that is over.  Both empty means offer nothing.
    """

    campaign: RegistrationCampaign | None = None
    cohort: Cohort | None = None

    def __bool__(self) -> bool:
        return self.campaign is not None


def family_registration(family: Course) -> FamilyRegistration:
    """Return the registration a course family offers, newest edition first.

    The donor orders editions by ``("-year", "-id")``; the package ``Cohort`` has no
    ``year``, so editions are ordered by ``start_date`` descending with nulls last,
    then ``-id``.
    """

    editions = list(
        family.cohorts.filter(visible=True).order_by(F("start_date").desc(nulls_last=True), "-id")
    )
    for cohort in editions:
        campaign = active_campaign_for_cohort(cohort)
        if campaign is not None:
            return FamilyRegistration(campaign=campaign, cohort=cohort)
    for cohort in editions:
        campaign = next_edition_campaign_for_cohort(cohort)
        if campaign is not None:
            return FamilyRegistration(campaign=campaign)
    return FamilyRegistration()


class RegistrationCampaignStateError(ValueError):
    """The campaign's ``current_cohort`` state does not allow this transition.

    A campaign is either promoting one cohort (``current_cohort`` set) or
    promoting nothing while it waits for the next edition ("future/none",
    ``current_cohort`` is ``None``).  Both write operations below fail closed
    rather than silently clobbering whichever state the campaign is actually
    in.
    """


def stop_registration(campaign: RegistrationCampaign) -> RegistrationCampaign:
    """Close registration for the cohort ``campaign`` currently promotes.

    Sets ``current_cohort`` to ``None`` -- the campaign's "future/none" state,
    from which :func:`open_new_cohort` can later open the next edition.  Fails
    closed when the campaign has nothing open to stop, rather than treating a
    repeated click as a harmless no-op.

    The donor records an ``AuditEvent`` here; the package fires the
    ``registration_campaign_stopped`` hook instead (audit rows stay a site
    concern).
    """

    with transaction.atomic():
        locked = RegistrationCampaign.objects.select_for_update().get(pk=campaign.pk)
        previous_cohort = locked.current_cohort
        if previous_cohort is None:
            raise RegistrationCampaignStateError(
                "This campaign has no open cohort to stop registration for."
            )
        locked.current_cohort = None
        locked.save(update_fields=["current_cohort", "updated_at"])
        hooks.registration_campaign_stopped(campaign=locked, previous_cohort=previous_cohort)
        return locked


def open_new_cohort(campaign: RegistrationCampaign, cohort: Cohort) -> RegistrationCampaign:
    """Open registration for ``cohort`` through ``campaign``.

    Only valid while the campaign is in the "future/none" state.  A campaign
    that is still promoting a cohort must be stopped first via
    :func:`stop_registration` -- this never silently repoints an open
    campaign out from under whoever is currently registering.

    The donor records an ``AuditEvent`` here; the package fires the
    ``registration_cohort_opened`` hook instead (audit rows stay a site
    concern).
    """

    if not isinstance(cohort, Cohort) or cohort.pk is None:
        raise RegistrationCampaignStateError("Choose an existing cohort to open registration for.")

    with transaction.atomic():
        locked = RegistrationCampaign.objects.select_for_update().get(pk=campaign.pk)
        if locked.current_cohort_id is not None:
            raise RegistrationCampaignStateError(
                "Stop registration for the current cohort before opening a new one."
            )
        locked.current_cohort = cohort
        locked.save(update_fields=["current_cohort", "updated_at"])
        hooks.registration_cohort_opened(campaign=locked, cohort=cohort)
        return locked


def campaign_course_is_open(campaign: RegistrationCampaign) -> bool:
    """Whether the cohort this campaign promotes has started delivering coursework.

    Openness is derived, never stored: the campaign carries no window dates.
    """

    cohort = campaign.current_cohort
    if cohort is None:
        return False

    return (
        Homework.objects.filter(cohort=cohort).exists()
        or Project.objects.filter(cohort=cohort).exists()
    )


@dataclass(frozen=True, slots=True)
class PublicCourseRegistrationCount:
    count: int


def public_course_registration_count(
    campaign: RegistrationCampaign,
) -> PublicCourseRegistrationCount | None:
    """The registration total for whichever cohort this campaign currently promotes.

    Always ``baseline (while it still applies) + count(native rows created at or
    after the native boundary, for the campaign's current cohort)``, computed
    live.  Returns ``None`` when the campaign has no current cohort -- there is
    nothing to count once a campaign stops promoting a specific edition.  The
    baseline applies only while ``registration_baseline_cohort`` names the
    campaign's current cohort; the moment the campaign promotes a different
    cohort, the baseline stops applying entirely.
    """

    cohort = campaign.current_cohort
    if cohort is None:
        return None
    baseline_count = 0
    native_start_at = None
    if campaign.registration_baseline_cohort_id == cohort.id:
        baseline_count = campaign.registration_baseline_count
        native_start_at = campaign.registration_native_start_at
    native_rows = CourseRegistration.objects.filter(campaign=campaign, cohort=cohort)
    if native_start_at is not None:
        native_rows = native_rows.filter(created_at__gte=native_start_at)
    return PublicCourseRegistrationCount(count=baseline_count + native_rows.count())


def create_course_registration(
    campaign: RegistrationCampaign,
    *,
    email: str,
    name: str,
    country: str,
    role: str,
    region_resolver=None,
    region: str = "",
    company_name: str = "",
    comment: str = "",
    accepted_newsletter: bool = True,
    user=None,
) -> CourseRegistration:
    """Create one registration snapshot for ``campaign``'s current cohort.

    The email is normalized (strip + lower) and the per-campaign uniqueness it
    implies is enforced with the donor's message; the same person can register
    for a later cohort through the same campaign once it rotates.  When
    ``region_resolver`` is given, ``region`` is ``region_resolver(country)``;
    the donor's country/region catalog is site content and DTC passes its
    resolver here.  ``cohort`` is left to the model's ``save()`` default so the
    row snapshots the cohort being promoted at registration time; later
    repointing never moves existing rows.  ``user`` is stored as given and no
    profile is touched -- account and profile updates are site/view concerns.
    Fires ``hooks.registration_created`` after save (the donor's datamailer
    sync and confirmation email are site integrations wired to that hook).
    """

    email_normalized = (email or "").strip().lower()
    if (
        email_normalized
        and CourseRegistration.objects.filter(
            campaign=campaign, email_normalized=email_normalized
        ).exists()
    ):
        raise ValidationError("You have already registered for this course.")
    if region_resolver is not None:
        region = region_resolver(country)
    registration = CourseRegistration(
        campaign=campaign,
        email=email_normalized,
        name=name,
        company_name=company_name,
        country=country,
        region=region,
        role=role,
        comment=comment,
        accepted_newsletter=accepted_newsletter,
        user=user,
    )
    registration.save()
    hooks.registration_created(registration=registration)
    return registration
