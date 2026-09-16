import json
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Prefetch, Q

from community_base.curriculum.rendering import render_markdown, strip_leading_title_h1
from community_base.curriculum.validators import (
    SHA1_PATTERN,
    SHA256_PATTERN,
    repository_branch_validator,
    repository_component_validator,
    sha1_validator,
    sha256_validator,
    source_path_validator,
    source_stable_id_validator,
    source_version_validator,
    validate_source_path,
)
from community_base.kernel.access import (
    LEVEL_BASIC,
    LEVEL_MAIN,
    LEVEL_OPEN,
    LEVEL_PREMIUM,
    LEVEL_REGISTERED,
)

STATUS_CHOICES = (
    ("draft", "Draft"),
    ("published", "Published"),
)
COHORT_MODES = (
    ("cohort", "Cohort"),
    ("self_paced", "Self-paced"),
)
UNIT_KIND_LESSON = "lesson"
UNIT_KIND_HOMEWORK = "homework"
UNIT_KIND_EVENT = "event"
UNIT_KINDS = (
    (UNIT_KIND_LESSON, "Lesson"),
    (UNIT_KIND_HOMEWORK, "Homework"),
    (UNIT_KIND_EVENT, "Event"),
)
SOURCE_MANUAL = "manual"
SOURCE_AUTO_PROGRESS = "auto_progress"
SOURCE_ADMIN = "admin"
ENROLLMENT_SOURCES = (
    (SOURCE_MANUAL, "Manual"),
    (SOURCE_AUTO_PROGRESS, "Auto (first lesson complete)"),
    (SOURCE_ADMIN, "Admin (Studio)"),
)
COURSE_LEVEL_CHOICES = (
    (LEVEL_OPEN, "Open (everyone)"),
    (LEVEL_BASIC, "Basic and above"),
    (LEVEL_MAIN, "Main and above"),
    (LEVEL_PREMIUM, "Premium only"),
)
UNIT_LEVEL_CHOICES = (
    (LEVEL_OPEN, "Open (everyone)"),
    (LEVEL_REGISTERED, "Registered users"),
    (LEVEL_BASIC, "Basic and above"),
    (LEVEL_MAIN, "Main and above"),
    (LEVEL_PREMIUM, "Premium only"),
)

_SHA1_BODY = SHA1_PATTERN.strip("^$")
_SHA256_BODY = SHA256_PATTERN.strip("^$")


def provenance_constraint(*, name: str, identity_fields: tuple[str, ...] = ("source_content_id",)):
    """All-or-nothing provenance: identity, path, commit and checksum move together."""

    fields = (*identity_fields, "source_path", "source_commit_sha", "source_checksum")
    absent = Q(**{f"{field}__isnull": True for field in fields})
    present = Q(**{f"{field}__isnull": False for field in fields})
    present &= Q(source_commit_sha__regex=_SHA1_BODY)
    present &= Q(source_checksum__regex=_SHA256_BODY)
    return models.CheckConstraint(condition=absent | present, name=name)


class SourceProvenanceMixin(models.Model):
    """Nullable provenance shared by source-managed curriculum records."""

    source_content_id = models.UUIDField(null=True, blank=True)
    source_path = models.CharField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=1024,
        null=True,
        blank=True,
        validators=[source_path_validator],
    )
    source_commit_sha = models.CharField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=40,
        null=True,
        blank=True,
        validators=[sha1_validator],
    )
    source_checksum = models.CharField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=64,
        null=True,
        blank=True,
        validators=[sha256_validator],
    )

    SOURCE_IDENTITY_FIELDS = ("source_content_id",)

    class Meta:
        abstract = True

    def clean(self) -> None:
        super().clean()
        field_names = (
            *self.SOURCE_IDENTITY_FIELDS,
            "source_path",
            "source_commit_sha",
            "source_checksum",
        )
        values = {field_name: getattr(self, field_name) for field_name in field_names}
        populated = {field_name for field_name, value in values.items() if value is not None}
        if populated and len(populated) != len(values):
            missing = sorted(set(values) - populated)
            raise ValidationError(
                {
                    field_name: "Source provenance must be supplied as a complete set."
                    for field_name in missing
                }
            )
        empty = {
            field_name
            for field_name, value in values.items()
            if value is not None and isinstance(value, str) and not value
        }
        if empty:
            raise ValidationError(
                {field_name: "Source provenance values cannot be empty." for field_name in empty}
            )
        if self.source_path:
            validate_source_path(self.source_path)


class Course(SourceProvenanceMixin, models.Model):
    """A reusable course: cohorts deliver it, modules and units teach it."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    slug = models.SlugField(max_length=300, unique=True)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    description_html = models.TextField(blank=True, default="", editable=False)
    cover_image_url = models.URLField(max_length=500, blank=True, default="")
    auto_banner_url = models.URLField(max_length=500, blank=True, default="")
    custom_banner_url = models.URLField(max_length=500, blank=True, default="")
    required_level = models.IntegerField(default=LEVEL_OPEN, choices=COURSE_LEVEL_CHOICES)
    default_unit_required_level = models.IntegerField(
        null=True,
        blank=True,
        choices=UNIT_LEVEL_CHOICES,
        help_text=(
            "Default access level applied to every unit in this course unless the unit "
            "overrides it. When null, units inherit Course.required_level."
        ),
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    discussion_url = models.URLField(max_length=500, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    testimonials = models.JSONField(default=list, blank=True)
    github_repo_url = models.URLField(max_length=500, blank=True, default="")
    docs_url = models.URLField(max_length=500, blank=True, default="")
    faq_url = models.URLField(max_length=500, blank=True, default="")
    hashtag = models.CharField(max_length=100, blank=True, default="")
    visible = models.BooleanField(default=True)
    instructors = models.ManyToManyField(
        "events.Host",
        through="CourseInstructor",
        related_name="courses",
        blank=True,
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.description:
            description_md = strip_leading_title_h1(self.description, self.title)
            self.description_html = render_markdown(description_md)
        else:
            self.description_html = ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "description" in update_fields:
                update_fields.add("description_html")
            kwargs["update_fields"] = list(update_fields)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f"/courses/{self.slug}"

    @property
    def is_published(self):
        return self.status == "published"

    @property
    def is_free(self):
        return self.required_level == LEVEL_OPEN

    @property
    def ordered_instructors(self):
        return list(self.instructors.order_by("course_instructor_links__position"))

    @property
    def primary_instructor(self):
        return self.instructors.order_by("course_instructor_links__position").first()

    def _countable_units(self):
        """Units that count toward the progress denominator.

        Every unit counts, including ``kind=event`` units, except a unit (or its module, or
        that module's parent module) marked ``is_bonus`` -- tracked and displayed, but
        excluded from the denominator (owner decision, community-base#252).
        """

        return (
            Unit.objects.filter(module__course=self)
            .exclude(is_bonus=True)
            .exclude(module__is_bonus=True)
            .exclude(module__parent__is_bonus=True)
        )

    def total_units(self):
        return self._countable_units().count()

    def completed_units(self, user):
        if user is None or not user.is_authenticated:
            return 0
        return UnitProgress.objects.filter(
            user=user,
            unit__in=self._countable_units(),
            completed_at__isnull=False,
        ).count()

    def get_syllabus(self):
        """Return cohorts, each carrying its effective modules as ``syllabus_modules``.

        A cohort's effective modules are its :class:`CohortModule` placements when it has
        any, otherwise the course's full top-level module tree (see
        :meth:`Cohort.effective_modules`) -- computed here in two queries total rather than
        one query per cohort.
        """

        cohorts = list(self.cohorts.order_by("start_date", "pk"))
        default_modules = list(
            self.modules.filter(parent__isnull=True)
            .prefetch_related(Prefetch("units", queryset=Unit.objects.order_by("sort_order", "pk")))
            .order_by("sort_order", "pk")
        )
        placements_by_cohort: dict[int, list[Module]] = {}
        placements = (
            CohortModule.objects.filter(cohort__in=cohorts)
            .select_related("module")
            .prefetch_related(
                Prefetch("module__units", queryset=Unit.objects.order_by("sort_order", "pk"))
            )
            .order_by("cohort_id", "sort_order", "pk")
        )
        for placement in placements:
            placements_by_cohort.setdefault(placement.cohort_id, []).append(placement.module)
        for cohort in cohorts:
            cohort.syllabus_modules = placements_by_cohort.get(cohort.pk) or default_modules
        return cohorts

    def get_next_unit_for(self, user):
        from community_base.curriculum.services import get_next_unit_for_user

        return get_next_unit_for_user(self, user)


class CourseInstructor(models.Model):
    """Through model linking Course -> events.Host with display order."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    host = models.ForeignKey(
        "events.Host", on_delete=models.PROTECT, related_name="course_instructor_links"
    )
    position = models.PositiveIntegerField(
        default=0,
        help_text="Display order; 0 is the primary instructor.",
    )

    class Meta:
        ordering = ("position",)
        constraints = [
            models.UniqueConstraint(fields=("course", "host"), name="cb_course_host_unique"),
        ]

    def __str__(self):
        return f"{self.course} - {self.host} (#{self.position})"


class Cohort(SourceProvenanceMixin, models.Model):
    """One delivery of a course: a dated cohort or the open-ended self-paced cohort."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="cohorts")
    slug = models.SlugField(max_length=300, default="")
    title = models.CharField(max_length=300)
    mode = models.CharField(max_length=20, choices=COHORT_MODES, default="cohort")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    registration_url = models.URLField(max_length=500, blank=True, default="")
    hashtag = models.CharField(max_length=100, blank=True, default="")
    finished = models.BooleanField(default=False)
    visible = models.BooleanField(default=True)
    max_participants = models.IntegerField(null=True, blank=True)
    project_passing_score = models.IntegerField(default=0)
    min_projects_to_pass = models.IntegerField(default=1)
    first_homework_scored = models.BooleanField(default=False)
    homework_problems_comments_field = models.BooleanField(default=False)

    class Meta:
        ordering = ("start_date", "pk")
        constraints = [
            models.UniqueConstraint(fields=("course", "slug"), name="cb_cohort_course_slug_unique"),
            models.UniqueConstraint(
                fields=("course",),
                condition=Q(mode="self_paced"),
                name="cb_cohort_self_paced_unique",
            ),
            provenance_constraint(name="cb_cohort_source_complete", identity_fields=()),
        ]

    def __str__(self):
        return f"{self.course.title} - {self.title}"

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be earlier than start date."})

    @property
    def enrollment_count(self):
        return self.enrollments.filter(unenrolled_at__isnull=True).count()

    @property
    def is_full(self):
        if self.max_participants is None:
            return False
        return self.enrollment_count >= self.max_participants

    @property
    def spots_remaining(self):
        if self.max_participants is None:
            return None
        return max(0, self.max_participants - self.enrollment_count)

    def effective_modules(self):
        """Return this cohort's top-level modules: its placements, or the full course tree.

        A cohort with no :class:`CohortModule` rows shows every top-level module of its
        course, in module order -- the common case (every AI Shipping Labs course today,
        one evergreen tree, no curation). A cohort with placement rows shows exactly that
        curated subset and order instead -- DataTalks.Club's case, where cohorts of the
        same course family genuinely differ year to year.
        """

        placements = list(
            CohortModule.objects.filter(cohort=self)
            .select_related("module")
            .order_by("sort_order", "pk")
        )
        if placements:
            return [placement.module for placement in placements]
        return list(Module.objects.filter(course_id=self.course_id, parent__isnull=True))


class Module(SourceProvenanceMixin, models.Model):
    """An ordered module of a course. A submodule is a module with ``parent`` set.

    A module holds either child modules or direct units, never both (enforced in
    :meth:`clean`, not a database constraint, because the rule spans two related
    tables -- ``children`` and ``units`` -- which a ``CheckConstraint`` cannot express).
    Nesting is capped at two module levels: a submodule cannot itself have children.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Set to make this module a submodule of another. Maximum two levels.",
    )
    slug = models.SlugField(max_length=300, default="")
    title = models.CharField(max_length=300)
    sort_order = models.IntegerField(default=0)
    overview = models.TextField(blank=True, default="")
    overview_html = models.TextField(blank=True, default="", editable=False)
    is_bonus = models.BooleanField(
        default=False,
        db_default=False,
        help_text="Optional enrichment, excluded from the progress denominator.",
    )
    available_after_days = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Cohort drip schedule for a top-level module: it (and its units, unless they "
            "override it themselves) becomes available this many days after the cohort "
            "start date. Null means no module-level offset."
        ),
    )

    class Meta:
        ordering = ("sort_order", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("course", "parent", "slug"),
                name="cb_module_course_parent_slug_unique",
            ),
            provenance_constraint(name="cb_module_source_complete", identity_fields=()),
        ]

    def __str__(self):
        return f"{self.course.title} - {self.title}"

    def save(self, *args, **kwargs):
        if self.overview:
            overview_md = strip_leading_title_h1(self.overview, self.title)
            self.overview_html = render_markdown(overview_md)
        else:
            self.overview_html = ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "overview" in update_fields:
                update_fields.add("overview_html")
            kwargs["update_fields"] = list(update_fields)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if self.parent_id is not None:
            if self.pk is not None and self.parent_id == self.pk:
                errors["parent"] = "A module cannot be its own parent."
            elif self.parent is not None:
                if self.parent.parent_id is not None:
                    errors["parent"] = "A submodule cannot itself have children (max two levels)."
                if self.course_id and self.parent.course_id != self.course_id:
                    errors["parent"] = "A parent module must belong to the same course."
                if self.parent.units.exists():
                    errors["parent"] = (
                        f"Module {self.parent.title!r} already has direct units; "
                        "it cannot also have child modules."
                    )
        if self.pk is not None:
            has_children = self.children.exists()
            has_units = self.units.exists()
            if has_children and has_units:
                errors["parent"] = (
                    f"Module {self.title!r} has both child modules and direct units; "
                    "it must have only one."
                )
        if errors:
            raise ValidationError(errors)

    @property
    def effective_is_bonus(self) -> bool:
        """Bonus cascades from an ancestor: a bonus week's submodules are bonus too."""

        if self.is_bonus:
            return True
        return bool(self.parent_id and self.parent.is_bonus)


class CohortModule(models.Model):
    """One cohort's placement of one top-level module, in that cohort's own order.

    Placements are optional. A cohort with none shows the full course tree (see
    :meth:`Cohort.effective_modules`); rows here exist only when a cohort needs to show a
    different subset, or a different order, of its course's top-level modules -- for
    example two cohorts of the same course family that each teach an alternative treatment
    of one topic as separate modules and each place only one of the two.
    """

    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="module_placements")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="placements")
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("cohort", "module"), name="cb_cohort_module_pair_unique"
            ),
            models.UniqueConstraint(
                fields=("cohort", "sort_order"), name="cb_cohort_module_sort_unique"
            ),
        ]

    def __str__(self):
        return f"{self.cohort} -> {self.module}"

    def clean(self):
        super().clean()
        errors: dict[str, str] = {}
        if self.module_id and self.module.parent_id is not None:
            errors["module"] = (
                "A placement targets a top-level module; a submodule is reached through its parent."
            )
        if self.cohort_id and self.module_id and self.module.course_id != self.cohort.course_id:
            errors["module"] = "A placement must reference a module of the cohort's own course."
        if errors:
            raise ValidationError(errors)


class Unit(SourceProvenanceMixin, models.Model):
    """A single lesson unit within a module."""

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="units")
    slug = models.SlugField(max_length=300, default="")
    title = models.CharField(max_length=300)
    sort_order = models.IntegerField(default=0)
    kind = models.CharField(
        max_length=20,
        choices=UNIT_KINDS,
        default=UNIT_KIND_LESSON,
        db_default=UNIT_KIND_LESSON,
    )
    session_position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Meaningful only when kind=event: this unit's 1-indexed position in the "
            "course's live-session series. Not a foreign key -- the real Event is "
            "resolved by the site, per viewer, against the viewer's own cohort."
        ),
    )
    is_bonus = models.BooleanField(
        default=False,
        db_default=False,
        help_text="Optional enrichment, excluded from the progress denominator.",
    )
    video_url = models.URLField(max_length=500, blank=True, default="")
    body = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="", editable=False)
    homework = models.TextField(blank=True, default="")
    homework_html = models.TextField(blank=True, default="", editable=False)
    timestamps = models.JSONField(default=list, blank=True)
    is_preview = models.BooleanField(default=False)
    required_level = models.IntegerField(null=True, blank=True, choices=UNIT_LEVEL_CHOICES)
    available_after_days = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Cohort drip schedule: the unit becomes available this many days after the "
            "cohort start date. Null means it falls back to its module's (or that "
            "module's parent module's) available_after_days, then to immediate."
        ),
    )
    content_hash = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        ordering = ("sort_order", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("module", "slug"),
                name="cb_unit_module_slug_unique",
            ),
            provenance_constraint(name="cb_unit_source_complete", identity_fields=()),
        ]

    def __str__(self):
        return f"{self.module.title} - {self.title}"

    def save(self, *args, **kwargs):
        if self.body:
            body_md = strip_leading_title_h1(self.body, self.title)
            self.body_html = render_markdown(body_md)
        else:
            self.body_html = ""
        if self.homework:
            self.homework_html = render_markdown(self.homework)
        else:
            self.homework_html = ""
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "body" in update_fields:
                update_fields.add("body_html")
            if "homework" in update_fields:
                update_fields.add("homework_html")
            kwargs["update_fields"] = list(update_fields)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.module_id and self.module.children.exists():
            raise ValidationError(
                {
                    "module": (
                        f"Module {self.module.title!r} has child modules; "
                        "it cannot also have direct units."
                    )
                }
            )

    @property
    def course(self):
        return self.module.course

    @property
    def effective_required_level(self):
        """Resolve the access level: unit override, course default, then course level."""

        if self.required_level is not None:
            return self.required_level
        course = self.module.course
        if course.default_unit_required_level is not None:
            return course.default_unit_required_level
        return course.required_level

    @property
    def effective_is_bonus(self) -> bool:
        """Bonus cascades from the unit's module (and that module's parent)."""

        if self.is_bonus:
            return True
        return self.module.effective_is_bonus

    @property
    def effective_available_after_days(self):
        """Resolve the drip offset: unit override, its module's, then its parent module's."""

        if self.available_after_days is not None:
            return self.available_after_days
        module = self.module
        if module.available_after_days is not None:
            return module.available_after_days
        if module.parent_id:
            return module.parent.available_after_days
        return None


class Enrollment(models.Model):
    """An explicit user-cohort enrollment with soft-delete for history."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="curriculum_enrollments",
    )
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)
    unenrolled_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, choices=ENROLLMENT_SOURCES, default="manual")
    display_name = models.CharField(max_length=255, blank=True, default="")
    display_on_leaderboard = models.BooleanField(default=True)
    display_public_profile = models.BooleanField(default=False)
    position_on_leaderboard = models.IntegerField(null=True, blank=True)
    disable_learning_in_public = models.BooleanField(default=False)
    certificate_name = models.CharField(max_length=255, blank=True, default="")
    total_score = models.IntegerField(default=0)
    certificate_url = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ("-enrolled_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "cohort"),
                condition=Q(unenrolled_at__isnull=True),
                name="cb_enrollment_active_unique",
            ),
        ]

    def __str__(self):
        state = "unenrolled" if self.unenrolled_at else "active"
        return f"{self.user} -> {self.cohort.title} ({state})"

    @property
    def is_active(self):
        return self.unenrolled_at is None


class UnitProgress(models.Model):
    """Tracks a user's completion of a unit."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="unit_progress",
    )
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "unit"),
                name="cb_unit_progress_user_unit_unique",
            ),
        ]

    def __str__(self):
        status = "completed" if self.completed_at else "in progress"
        return f"{self.user} - {self.unit} ({status})"


class Certificate(models.Model):
    """A completion certificate for one enrollment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.OneToOneField(
        Enrollment, on_delete=models.CASCADE, related_name="certificate"
    )
    url = models.URLField(max_length=500, blank=True, default="")
    issued_at = models.DateTimeField(auto_now_add=True)
    hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ("-issued_at",)

    def __str__(self):
        return f"Certificate: {self.enrollment}"

    def get_absolute_url(self):
        return f"/certificates/{self.pk}"


class CurriculumImportRun(models.Model):
    """Bounded, redacted evidence for one source import attempt."""

    class State(models.TextChoices):
        RECEIVED = "received", "Received"
        VALIDATING = "validating", "Validating"
        APPLYING = "applying", "Applying"
        SUCCEEDED = "succeeded", "Succeeded"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    MAX_DIAGNOSTICS = 100
    MAX_DIAGNOSTICS_BYTES = 65_536
    MAX_COUNT_KEYS = 100
    MAX_COUNTS_BYTES = 16_384

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_uuid = models.UUIDField()
    source_stable_id = models.CharField(max_length=128, validators=[source_stable_id_validator])
    repository_owner = models.CharField(
        max_length=128,
        validators=[repository_component_validator],
    )
    repository_name = models.CharField(
        max_length=128,
        validators=[repository_component_validator],
    )
    repository_branch = models.CharField(max_length=255, validators=[repository_branch_validator])
    commit_sha = models.CharField(max_length=40, validators=[sha1_validator])
    schema_version = models.PositiveIntegerField()
    parser_version = models.CharField(max_length=128, validators=[source_version_validator])
    state = models.CharField(max_length=16, choices=State.choices, default=State.RECEIVED)
    manifest_checksum = models.CharField(  # noqa: DJ001 -- absent until calculated.
        max_length=64,
        null=True,
        blank=True,
        validators=[sha256_validator],
    )
    diagnostics = models.JSONField(default=list, blank=True)
    counts = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("source_uuid", "commit_sha", "parser_version"),
                name="cb_curriculum_import_identity_uq",
            ),
            models.CheckConstraint(
                condition=Q(commit_sha__regex=_SHA1_BODY),
                name="cb_curriculum_import_commit_ck",
            ),
            models.CheckConstraint(
                condition=Q(manifest_checksum__isnull=True)
                | Q(manifest_checksum__regex=_SHA256_BODY),
                name="cb_curriculum_import_manifest_ck",
            ),
            models.CheckConstraint(
                condition=Q(schema_version__gte=1),
                name="cb_curriculum_import_schema_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=("source_uuid", "state", "-created_at"),
                name="cb_curr_import_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_stable_id}@{self.commit_sha[:12]} ({self.state})"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if not isinstance(self.diagnostics, list):
            errors["diagnostics"] = "Diagnostics must be a list."
        elif len(self.diagnostics) > self.MAX_DIAGNOSTICS:
            errors["diagnostics"] = "Diagnostics exceed the item limit."
        elif any(not isinstance(item, dict) for item in self.diagnostics):
            errors["diagnostics"] = "Each diagnostic must be an object."
        elif self._json_size(self.diagnostics) > self.MAX_DIAGNOSTICS_BYTES:
            errors["diagnostics"] = "Diagnostics exceed the encoded size limit."

        if not isinstance(self.counts, dict):
            errors["counts"] = "Counts must be an object."
        elif len(self.counts) > self.MAX_COUNT_KEYS:
            errors["counts"] = "Counts exceed the key limit."
        elif any(
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for key, value in self.counts.items()
        ):
            errors["counts"] = "Counts require canonical keys and non-negative integers."
        elif self._json_size(self.counts) > self.MAX_COUNTS_BYTES:
            errors["counts"] = "Counts exceed the encoded size limit."

        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            errors["finished_at"] = "Finished time cannot be earlier than started time."
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _json_size(value) -> int:
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return 2**63 - 1
        return len(encoded.encode("utf-8"))
