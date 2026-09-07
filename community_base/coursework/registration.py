"""Registration campaigns: bindings, counts, rows and the cohort state machine.

A cohort registers through a campaign either because the campaign promotes it
now (``current_cohort``) or because its own ``registration_url`` names the
campaign for whatever runs next. Nothing is derived: a URL that is not a
campaign path, or that names no campaign in this database, resolves to
nothing and the caller offers no registration rather than guessing.

Donor mapping (``courses/services/registration_campaigns.py``,
``registration_counts.py``): the donor ``course`` argument is the package
``Cohort``, donor ``current_course`` is ``current_cohort`` and donor
``Enrollment.student`` is ``Enrollment.user``. The package ``Cohort`` carries
no ``year`` field, so course families order editions by ``-start_date, -pk``
where the donor ordered ``-year, -id``. Analytics and audit writes fire
through ``coursework.hooks`` and stay site-configured; newsletter consent is
optional evidence passed by the caller, and countries/region derivation stays
with the site registration views.
"""

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from community_base.coursework.hooks import hooks
from community_base.coursework.models import (
    CourseRegistration,
    Homework,
    Project,
    RegistrationCampaign,
)
from community_base.curriculum.models import Cohort

# The registration platform's own public registration path. The host is
# deliberately unconstrained: what is read is the campaign slug the platform
# published, not the origin it published it on.
_CAMPAIGN_PATH = re.compile(
    r"^https?://[^/]+/register/(?P<slug>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/?$"
)


class RegistrationCampaignStateError(Exception):
    """The campaign's ``current_cohort`` state does not allow this transition.

    A campaign is either promoting one cohort (``current_cohort`` set) or
    promoting nothing while it waits for the next edition. Both write
    operations below fail closed rather than silently clobbering whichever
    state the campaign is actually in.
    """


@dataclass(frozen=True)
class FamilyRegistration:
    """What a course family currently offers a visitor who wants to register.

    ``cohort`` is set only when a campaign is promoting that exact edition,
    which is the one case where naming an edition is honest. A family whose
    editions have all closed keeps the campaign and drops the edition, so the
    page can say "the next edition" without naming a cohort that is over.
    Both empty means offer nothing.
    """

    campaign: RegistrationCampaign | None = None
    cohort: Cohort | None = None

    def __bool__(self) -> bool:
        return self.campaign is not None


def public_course_registration_count(campaign) -> int | None:
    """The registration total for whichever cohort this campaign promotes.

    Returns ``None`` when the campaign has no current cohort -- there is
    nothing to count once a campaign stops promoting a specific edition.
    The count is the recorded baseline plus the native ``CourseRegistration``
    rows for the current cohort. The baseline applies only while it names the
    campaign's current cohort (a baseline for a finished edition never
    carries onto the next one), and while it applies, rows created before
    ``registration_native_start_at`` are excluded so pre-import rows never
    double-count the baseline.
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
    return baseline_count + native_rows.count()


def campaign_slug_in_registration_url(url: str) -> str:
    """Return the campaign slug a registration URL names, or an empty string."""

    if not url:
        return ""
    match = _CAMPAIGN_PATH.match(url.strip())
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

    Only meaningful when no campaign promotes this edition: it is the waiting
    list for whatever runs next. A campaign that does promote this edition is
    returned by :func:`active_campaign_for_cohort` instead, so this never
    duplicates it.
    """

    slug = campaign_slug_in_registration_url(cohort.registration_url)
    if not slug:
        return None
    campaign = RegistrationCampaign.objects.filter(slug=slug, is_active=True).first()
    if campaign is None or campaign.current_cohort_id == cohort.id:
        return None
    return campaign


def family_registration(course) -> FamilyRegistration | None:
    """Return the registration a course family offers, newest edition first."""

    editions = list(course.cohorts.filter(visible=True).order_by("-start_date", "-pk"))
    for cohort in editions:
        campaign = active_campaign_for_cohort(cohort)
        if campaign is not None:
            return FamilyRegistration(campaign=campaign, cohort=cohort)
    for cohort in editions:
        campaign = next_edition_campaign_for_cohort(cohort)
        if campaign is not None:
            return FamilyRegistration(campaign=campaign)
    return FamilyRegistration()


def campaign_course_is_open(cohort: Cohort) -> bool:
    """Whether the promoted cohort actually has course content to start on."""

    return (
        Homework.objects.filter(cohort=cohort).exists()
        or Project.objects.filter(cohort=cohort).exists()
    )


def existing_course_registration(campaign, user, email) -> CourseRegistration | None:
    """Return the caller's registration in this campaign, if one exists.

    An authenticated caller matches on their account or their normalized
    email; an anonymous caller matches on the normalized email alone.
    """

    email_normalized = (email or "").strip().lower()
    identity = Q(email_normalized=email_normalized)
    if user is not None and getattr(user, "is_authenticated", True):
        identity |= Q(user=user)
    return CourseRegistration.objects.filter(campaign=campaign).filter(identity).first()


def create_course_registration(
    campaign,
    *,
    email: str,
    name: str,
    country: str,
    region: str,
    role: str,
    company_name: str = "",
    comment: str = "",
    accepted_newsletter: bool = False,
    user=None,
    cohort: Cohort | None = None,
) -> CourseRegistration:
    """Create one registration row and fire ``registration_submitted``.

    The email is normalized on save by the model; a duplicate normalized
    email within the campaign is rejected. ``cohort`` defaults to the
    campaign's current cohort (snapshotted by the model on save) and may be
    passed explicitly to override that snapshot. The submitted hook fires
    synchronously after the save, mirroring the donor's synchronous analytics
    event; emails and profile updates stay site-side.
    """

    email_normalized = (email or "").strip().lower()
    if CourseRegistration.objects.filter(
        campaign=campaign, email_normalized=email_normalized
    ).exists():
        raise ValidationError("You have already registered for this course.")

    registration = CourseRegistration(
        campaign=campaign,
        email=email or "",
        name=name,
        country=country,
        region=region,
        role=role,
        company_name=company_name,
        comment=comment,
        accepted_newsletter=accepted_newsletter,
        user=user,
        cohort=cohort,
    )
    registration.save()
    hooks.registration_submitted(registration=registration)
    return registration


def stop_registration(campaign, *, using=None) -> RegistrationCampaign:
    """Close registration for the cohort this campaign currently promotes.

    Sets ``current_cohort`` to ``None`` -- the campaign's waiting state, from
    which :func:`open_new_cohort` can later open the next edition. Fails
    closed when the campaign has nothing open to stop, rather than treating a
    repeated click as a harmless no-op.
    """

    with transaction.atomic(using=using):
        locked = RegistrationCampaign.objects.using(using).select_for_update().get(pk=campaign.pk)
        previous_cohort = locked.current_cohort
        if previous_cohort is None:
            raise RegistrationCampaignStateError(
                "This campaign has no open cohort to stop registration for."
            )
        locked.current_cohort = None
        locked.save(using=using, update_fields=("current_cohort", "updated_at"))
        hooks.registration_campaign_changed(
            campaign=locked,
            action="registration_stopped",
            previous_cohort=previous_cohort,
            current_cohort=None,
        )
        return locked


def open_new_cohort(campaign, cohort: Cohort, *, using=None) -> RegistrationCampaign:
    """Open registration for ``cohort`` through this campaign.

    Only valid while the campaign is in the waiting state. A campaign that is
    still promoting a cohort must be stopped first via
    :func:`stop_registration` -- this never silently repoints an open
    campaign out from under whoever is currently registering.
    """

    if cohort is None or cohort.pk is None:
        raise RegistrationCampaignStateError("Choose an existing cohort to open registration for.")

    with transaction.atomic(using=using):
        locked = RegistrationCampaign.objects.using(using).select_for_update().get(pk=campaign.pk)
        if locked.current_cohort_id is not None:
            raise RegistrationCampaignStateError(
                "Stop registration for the current cohort before opening a new one."
            )
        locked.current_cohort = cohort
        locked.save(using=using, update_fields=("current_cohort", "updated_at"))
        hooks.registration_campaign_changed(
            campaign=locked,
            action="cohort_opened",
            previous_cohort=None,
            current_cohort=cohort,
        )
        return locked
