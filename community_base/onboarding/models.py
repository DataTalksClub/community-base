from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class OnboardingFlow(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("title", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("is_default",),
                condition=Q(is_default=True),
                name="cb_onboarding_one_default_flow",
            ),
        )

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)


class OnboardingStep(models.Model):
    class Kind(models.TextChoices):
        PROFILE = "profile", "Profile"
        QUESTIONNAIRE = "questionnaire", "Questionnaire"
        AI_CHAT = "ai_chat", "AI chat"
        PLAN = "plan", "Plan"
        CUSTOM = "custom", "Custom"

    flow = models.ForeignKey(OnboardingFlow, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    config = models.JSONField(default=dict, blank=True)
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ("order", "pk")
        constraints = (
            models.UniqueConstraint(
                fields=("flow", "order"), name="cb_onboarding_unique_step_order"
            ),
        )

    def __str__(self):
        return f"{self.flow}: {self.get_kind_display()}"

    def clean(self):
        super().clean()
        if not isinstance(self.config, dict):
            raise ValidationError({"config": "Step config must be a JSON object."})
        if self.kind == self.Kind.QUESTIONNAIRE and not (
            self.config.get("persona_selection")
            or str(self.config.get("questionnaire_slug", "")).strip()
        ):
            raise ValidationError(
                {"config": "Questionnaire steps need questionnaire_slug or persona_selection."}
            )
        if self.kind == self.Kind.CUSTOM and not str(self.config.get("template", "")).strip():
            raise ValidationError({"config": "Custom steps need a template."})


class FlowAssignment(models.Model):
    flow = models.ForeignKey(OnboardingFlow, on_delete=models.CASCADE, related_name="assignments")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)
    min_level = models.PositiveSmallIntegerField(null=True, blank=True)
    priority = models.IntegerField(default=0)

    class Meta:
        ordering = ("-priority", "pk")
        constraints = (
            models.CheckConstraint(
                condition=Q(group__isnull=False) | Q(min_level__isnull=False),
                name="cb_onboarding_assignment_has_rule",
            ),
        )

    def __str__(self):
        return f"{self.flow} ({self.priority})"

    def clean(self):
        super().clean()
        if self.group_id is None and self.min_level is None:
            raise ValidationError("Choose a group or minimum access level.")


class OnboardingProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="onboarding_progress"
    )
    flow = models.ForeignKey(
        OnboardingFlow, on_delete=models.CASCADE, related_name="progress_records"
    )
    current_step = models.ForeignKey(
        OnboardingStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_progress_records",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-pk",)
        constraints = (
            models.UniqueConstraint(
                fields=("user", "flow"), name="cb_onboarding_unique_user_flow_progress"
            ),
        )

    def __str__(self):
        return f"{self.user_id}: {self.flow}"

    def clean(self):
        super().clean()
        if self.current_step_id and self.current_step.flow_id != self.flow_id:
            raise ValidationError({"current_step": "Current step must belong to the flow."})
        if not isinstance(self.data, dict):
            raise ValidationError({"data": "Progress data must be a JSON object."})
