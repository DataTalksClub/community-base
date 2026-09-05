from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

PURPOSE_CHOICES = (
    ("onboarding", "Onboarding"),
    ("feedback", "Feedback"),
    ("general", "General"),
)
QUESTION_TYPE_CHOICES = (
    ("text", "Short text"),
    ("long_text", "Long text"),
    ("single_choice", "Single choice"),
    ("multiple_choice", "Multiple choice"),
    ("scale", "Scale / rating"),
    ("number", "Number"),
)
RESPONSE_STATUS_CHOICES = (("draft", "Draft"), ("submitted", "Submitted"))
CHOICE_TYPES = frozenset({"single_choice", "multiple_choice"})


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Questionnaire(TimestampedModel):
    title = models.CharField(max_length=300)
    slug = models.SlugField(unique=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default="general")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    @property
    def question_count(self):
        return self.questions.count()

    @property
    def response_count(self):
        return self.responses.count()


class Persona(TimestampedModel):
    name = models.CharField(max_length=120)
    archetype = models.CharField(
        max_length=200,
        help_text=(
            "Short label shown next to the name everywhere in Studio, "
            'e.g. "The Engineer transitioning to AI". Required.'
        ),
    )
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, default="")
    default_questionnaire = models.ForeignKey(
        "questionnaires.Questionnaire",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="personas",
        help_text="Optional default onboarding questionnaire for this persona.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "name")

    def __str__(self):
        return self.display_label

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def display_label(self):
        return f"{self.name} — {self.archetype}"


class Question(TimestampedModel):
    questionnaire = models.ForeignKey(
        Questionnaire, on_delete=models.CASCADE, related_name="questions"
    )
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES)
    prompt = models.TextField()
    help_text = models.TextField(blank=True, default="")
    is_required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    scale_min = models.IntegerField(null=True, blank=True)
    scale_max = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.prompt[:80]

    @property
    def is_choice_type(self):
        return self.question_type in CHOICE_TYPES


class QuestionOption(TimestampedModel):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    label = models.CharField(max_length=300)
    allows_free_text = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.label


class Response(TimestampedModel):
    questionnaire = models.ForeignKey(
        Questionnaire, on_delete=models.CASCADE, related_name="responses"
    )
    respondent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="questionnaire_responses",
    )
    status = models.CharField(max_length=20, choices=RESPONSE_STATUS_CHOICES, default="draft")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_questionnaire_responses",
    )

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("questionnaire", "respondent"),
                name="unique_response_per_respondent_per_questionnaire",
            ),
            models.CheckConstraint(
                condition=Q(status="submitted")
                | (Q(reviewed_at__isnull=True) & Q(reviewed_by__isnull=True)),
                name="response_draft_review_fields_null",
            ),
            models.CheckConstraint(
                condition=Q(reviewed_by__isnull=True) | Q(reviewed_at__isnull=False),
                name="response_reviewer_requires_timestamp",
            ),
        )
        indexes = (
            models.Index(
                fields=("status", "reviewed_at", "-submitted_at"),
                name="response_review_queue_idx",
            ),
        )

    def __str__(self):
        return f"{self.respondent} -> {self.questionnaire}"

    def mark_submitted(self):
        self.status = "submitted"
        self.submitted_at = timezone.now()
        self.reviewed_at = None
        self.reviewed_by = None
        self.save(
            update_fields=(
                "status",
                "submitted_at",
                "reviewed_at",
                "reviewed_by",
                "updated_at",
            )
        )
        return self

    @property
    def review_state(self):
        if self.status != "submitted":
            return "not_applicable"
        return "awaiting" if self.reviewed_at is None else "reviewed"

    @property
    def review_label(self):
        if self.review_state == "not_applicable":
            return "Not applicable"
        if self.review_state == "awaiting":
            return "Awaiting review"
        if self.reviewed_by_id is None:
            return "Reviewed before queue launch"
        return "Reviewed"


class ResponseQuestion(TimestampedModel):
    response = models.ForeignKey(
        Response, on_delete=models.CASCADE, related_name="response_questions"
    )
    source_question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="response_questions",
    )
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES)
    prompt = models.TextField()
    help_text = models.TextField(blank=True, default="")
    is_required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    scale_min = models.IntegerField(null=True, blank=True)
    scale_max = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.prompt[:80]

    @property
    def is_choice_type(self):
        return self.question_type in CHOICE_TYPES

    @property
    def is_custom(self):
        return self.source_question_id is None


class ResponseQuestionOption(TimestampedModel):
    response_question = models.ForeignKey(
        ResponseQuestion, on_delete=models.CASCADE, related_name="options"
    )
    source_option = models.ForeignKey(
        QuestionOption, on_delete=models.SET_NULL, null=True, blank=True
    )
    label = models.CharField(max_length=300)
    allows_free_text = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")

    def __str__(self):
        return self.label


class Answer(TimestampedModel):
    response = models.ForeignKey(Response, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(ResponseQuestion, on_delete=models.CASCADE, related_name="answers")
    text_value = models.TextField(blank=True, default="")
    number_value = models.IntegerField(null=True, blank=True)
    selected_options = models.ManyToManyField(
        ResponseQuestionOption, blank=True, related_name="answers"
    )

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("response", "question"),
                name="unique_answer_per_question_per_response",
            ),
        )

    def __str__(self):
        return f"Answer to {self.question_id} in response {self.response_id}"

    @property
    def display_value(self):
        if self.question.question_type in CHOICE_TYPES:
            option_texts = {
                item.selected_option_id: item.text_value for item in self.option_texts.all()
            }
            values = []
            for option in self.selected_options.all():
                free_text = (option_texts.get(option.pk) or "").strip()
                values.append(f"{option.label}: {free_text}" if free_text else option.label)
            return ", ".join(values)
        if self.question.question_type in {"scale", "number"}:
            return "" if self.number_value is None else str(self.number_value)
        return self.text_value or ""


class AnswerOptionText(TimestampedModel):
    answer = models.ForeignKey(Answer, on_delete=models.CASCADE, related_name="option_texts")
    selected_option = models.ForeignKey(
        ResponseQuestionOption, on_delete=models.CASCADE, related_name="answer_texts"
    )
    text_value = models.TextField(blank=True, default="")

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("answer", "selected_option"), name="unique_text_per_answer_option"
            ),
        )

    def __str__(self):
        return f"Text for option {self.selected_option_id} on answer {self.answer_id}"


class OnboardingConversation(TimestampedModel):
    response = models.OneToOneField(
        Response, on_delete=models.CASCADE, related_name="ai_conversation"
    )
    transcript = models.JSONField(default=list, blank=True)
    persona_signal = models.CharField(max_length=20, blank=True, default="")
    turn_version = models.PositiveBigIntegerField(default=0, db_default=0)

    def __str__(self):
        return f"AI onboarding conversation for response {self.response_id}"

    def append_turn(self, role, content):
        if not isinstance(self.transcript, list):
            self.transcript = []
        self.transcript.append({"role": role, "content": content})
        return self.transcript


class OnboardingTurnAttempt(TimestampedModel):
    TRANSPORT_CHOICES = (("stream", "Stream"), ("non_stream", "Non-stream"))
    STATUS_CHOICES = (
        ("processing", "Processing"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    )
    NOTIFICATION_STATUS_CHOICES = (
        ("not_needed", "Not needed"),
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    )

    conversation = models.ForeignKey(
        OnboardingConversation, on_delete=models.CASCADE, related_name="turn_attempts"
    )
    request_id = models.UUIDField()
    member_message_hash = models.CharField(max_length=64)
    admitted_version = models.PositiveBigIntegerField()
    transport = models.CharField(max_length=16, choices=TRANSPORT_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="processing")
    outcome = models.CharField(max_length=32, blank=True, default="")
    error_code = models.CharField(max_length=32, blank=True, default="")
    provider = models.CharField(max_length=32, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    provider_call_count = models.PositiveSmallIntegerField(default=0)
    retry_count = models.PositiveSmallIntegerField(default=0)
    fallback_used = models.BooleanField(default=False)
    timed_out = models.BooleanField(default=False)
    disconnected = models.BooleanField(default=False)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    cache_read_tokens = models.PositiveIntegerField(null=True, blank=True)
    cache_write_tokens = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField()
    provider_started_at = models.DateTimeField(null=True, blank=True)
    first_delta_at = models.DateTimeField(null=True, blank=True)
    last_delta_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField()
    admission_to_provider_ms = models.PositiveIntegerField(null=True, blank=True)
    ttft_ms = models.PositiveIntegerField(null=True, blank=True)
    provider_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    persistence_tail_ms = models.PositiveIntegerField(null=True, blank=True)
    persistence_to_done_ms = models.PositiveIntegerField(null=True, blank=True)
    total_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    notification_status = models.CharField(
        max_length=16, choices=NOTIFICATION_STATUS_CHOICES, default="not_needed"
    )
    notification_attempt_count = models.PositiveSmallIntegerField(default=0)
    notification_lease_expires_at = models.DateTimeField(null=True, blank=True)
    notification_last_error = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("conversation", "request_id"), name="unique_onboarding_turn_request"
            ),
            models.UniqueConstraint(
                fields=("conversation",),
                condition=Q(status="processing"),
                name="one_processing_onboarding_turn",
            ),
        )
        indexes = (
            models.Index(
                fields=("status", "lease_expires_at"), name="questionnai_status_1aef50_idx"
            ),
        )

    def __str__(self):
        return f"Onboarding turn {self.request_id} ({self.status})"
