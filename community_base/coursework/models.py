import math
import statistics
from enum import Enum

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from community_base.coursework.stat_display import (
    build_stat_fields,
    homework_stat_sections,
    project_stat_sections,
)
from community_base.coursework.validators import validate_review_criteria_options
from community_base.curriculum.models import (
    Cohort,
    Course,
    Enrollment,
    SourceProvenanceMixin,
    provenance_constraint,
)
from community_base.curriculum.validators import source_stable_id_validator

URL_SCHEMES_WEB = URLValidator(schemes=["http", "https"])
URL_SCHEMES_GIT = URLValidator(schemes=["http", "https", "git"])


class HomeworkState(Enum):
    CLOSED = "CL"
    OPEN = "OP"
    SCORED = "SC"


HOMEWORK_STATE_CHOICES = [(state.value, state.name) for state in HomeworkState]


class Homework(SourceProvenanceMixin, models.Model):
    """One homework assignment belonging to a cohort."""

    slug = models.SlugField(blank=False)

    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="homeworks")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    instructions_markdown = models.TextField(blank=True)
    instructions_source_path = models.CharField(max_length=1024, blank=True, default="")
    instructions_url = models.URLField(  # noqa: DJ001 -- null means the link is unset.
        blank=True, null=True, validators=[URL_SCHEMES_WEB]
    )
    due_date = models.DateTimeField()

    learning_in_public_cap = models.IntegerField(default=7)

    homework_url_field = models.BooleanField(default=True)
    time_spent_lectures_field = models.BooleanField(default=True)
    time_spent_homework_field = models.BooleanField(default=True)
    faq_contribution_field = models.BooleanField(default=True)

    state = models.CharField(max_length=2, choices=HOMEWORK_STATE_CHOICES, default="OP")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("cohort", "slug"), name="cb_homework_cohort_slug_uq"),
            provenance_constraint(name="cb_homework_source_complete"),
        ]

    def __str__(self):
        return f"{self.cohort.title} - {self.title}"

    def is_scored(self):
        return self.state == HomeworkState.SCORED.value


class QuestionTypes(Enum):
    MULTIPLE_CHOICE = "MC"
    FREE_FORM = "FF"
    FREE_FORM_LONG = "FL"
    CHECKBOXES = "CB"


class AnswerTypes(Enum):
    ANY = "ANY"
    FLOAT = "FLT"
    INTEGER = "INT"
    EXACT_STRING = "EXS"
    CONTAINS_STRING = "CTS"


QUESTION_ANSWER_DELIMITER = "\n"

QUESTION_TYPES = (
    (QuestionTypes.MULTIPLE_CHOICE.value, "Multiple Choice"),
    (QuestionTypes.FREE_FORM.value, "Free Form"),
    (QuestionTypes.FREE_FORM_LONG.value, "Free Form Long"),
    (QuestionTypes.CHECKBOXES.value, "Checkboxes"),
)
ANSWER_TYPES = (
    (AnswerTypes.ANY.value, "Any"),
    (AnswerTypes.FLOAT.value, "Float"),
    (AnswerTypes.INTEGER.value, "Integer"),
    (AnswerTypes.EXACT_STRING.value, "Exact String"),
    (AnswerTypes.CONTAINS_STRING.value, "Contains String"),
)


class Question(SourceProvenanceMixin, models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    question_type = models.CharField(max_length=2, choices=QUESTION_TYPES)
    answer_type = models.CharField(  # noqa: DJ001 -- null means the answer type is unset.
        max_length=3, choices=ANSWER_TYPES, blank=True, null=True
    )
    possible_answers = models.TextField(blank=True, null=True)  # noqa: DJ001 -- donor shape.
    correct_answer = models.TextField(blank=True, null=True)  # noqa: DJ001 -- donor shape.
    source_question_id = models.SlugField(  # noqa: DJ001 -- null identifies DB-managed rows.
        max_length=128,
        null=True,
        blank=True,
        validators=[source_stable_id_validator],
    )
    source_option_ids = models.JSONField(null=True, blank=True)
    answer_envelope = models.JSONField(null=True, blank=True)
    scores_for_correct_answer = models.IntegerField(default=1)

    SOURCE_IDENTITY_FIELDS = ("source_content_id", "source_question_id")

    class Meta:
        constraints = [
            provenance_constraint(
                name="cb_question_source_complete",
                identity_fields=("source_content_id", "source_question_id"),
            ),
            models.UniqueConstraint(
                fields=("homework", "source_content_id"),
                condition=Q(source_content_id__isnull=False),
                name="cb_question_source_content_uq",
            ),
            models.UniqueConstraint(
                fields=("homework", "source_question_id"),
                condition=Q(source_question_id__isnull=False),
                name="cb_question_source_stable_uq",
            ),
        ]

    def __str__(self):
        return f"{self.homework.cohort.title} / {self.homework.title} - {self.text}"

    def clean(self):
        super().clean()
        if self.source_option_ids is not None:
            if (
                not isinstance(self.source_option_ids, list)
                or not self.source_option_ids
                or any(
                    not isinstance(option_id, str) or not option_id
                    for option_id in self.source_option_ids
                )
                or len(set(self.source_option_ids)) != len(self.source_option_ids)
            ):
                raise ValidationError(
                    {"source_option_ids": "Source option IDs must be unique strings."}
                )
        if self.answer_envelope is not None and not isinstance(self.answer_envelope, dict):
            raise ValidationError({"answer_envelope": "Answer envelope must be an object."})

    def get_possible_answers(self):
        if not self.possible_answers:
            return []
        return [
            raw_answer.strip()
            for raw_answer in self.possible_answers.split(QUESTION_ANSWER_DELIMITER)
        ]

    def has_choice_answers(self):
        return self.question_type in {
            QuestionTypes.CHECKBOXES.value,
            QuestionTypes.MULTIPLE_CHOICE.value,
        }

    def zero_based_correct_answer_indices(self):
        correct_answer = self.resolved_correct_answer()
        if not correct_answer:
            return []
        return [int(index_raw) - 1 for index_raw in correct_answer.split(",")]

    def get_choice_correct_answer(self):
        possible_answers = self.get_possible_answers()
        return {possible_answers[index] for index in self.zero_based_correct_answer_indices()}

    def get_correct_answer(self):
        if self.has_choice_answers():
            return self.get_choice_correct_answer()
        return self.resolved_correct_answer()

    def get_correct_answer_indices(self):
        correct_answer = self.resolved_correct_answer()
        if not correct_answer:
            return set()
        return {int(index_raw) for index_raw in correct_answer.split(",")}

    def resolved_correct_answer(self):
        from community_base.coursework.answer_resolution import resolve_correct_answer

        return resolve_correct_answer(self)


class Submission(models.Model):
    """A learner's homework submission and its scores."""

    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="homework_submissions"
    )
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="homework_submissions"
    )

    homework_link = models.URLField(  # noqa: DJ001 -- null means the link is unset.
        blank=True, null=True, validators=[URL_SCHEMES_GIT]
    )
    learning_in_public_links = models.JSONField(
        blank=True,
        null=True,
        help_text="Links where students talk about the course",
    )
    time_spent_lectures = models.FloatField(null=True, blank=True)
    time_spent_homework = models.FloatField(null=True, blank=True)
    problems_comments = models.TextField(blank=True)
    faq_contribution = models.TextField(blank=True)
    faq_contribution_url = models.URLField(  # noqa: DJ001 -- null means the link is unset.
        blank=True, null=True
    )

    submitted_at = models.DateTimeField(default=timezone.now)

    questions_score = models.IntegerField(default=0)
    faq_score = models.IntegerField(default=0)
    learning_in_public_score = models.IntegerField(default=0)
    total_score = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.student}'s submission for {self.homework.title}"


class Answer(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    answer_text = models.TextField(blank=True, null=True)  # noqa: DJ001 -- donor shape.  # noqa: DJ001 -- donor shape.
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"Answer id={self.id} for {self.question}"


class HomeworkStatistics(models.Model):
    homework = models.OneToOneField(Homework, on_delete=models.CASCADE, related_name="statistics")

    total_submissions = models.IntegerField(default=0)

    min_questions_score = models.IntegerField(null=True, blank=True)
    max_questions_score = models.IntegerField(null=True, blank=True)
    avg_questions_score = models.FloatField(null=True, blank=True)
    median_questions_score = models.FloatField(null=True, blank=True)
    q1_questions_score = models.FloatField(null=True, blank=True)
    q3_questions_score = models.FloatField(null=True, blank=True)

    min_total_score = models.IntegerField(null=True, blank=True)
    max_total_score = models.IntegerField(null=True, blank=True)
    avg_total_score = models.FloatField(null=True, blank=True)
    median_total_score = models.FloatField(null=True, blank=True)
    q1_total_score = models.FloatField(null=True, blank=True)
    q3_total_score = models.FloatField(null=True, blank=True)

    min_learning_in_public_score = models.IntegerField(null=True, blank=True)
    max_learning_in_public_score = models.IntegerField(null=True, blank=True)
    avg_learning_in_public_score = models.FloatField(null=True, blank=True)
    median_learning_in_public_score = models.FloatField(null=True, blank=True)
    q1_learning_in_public_score = models.FloatField(null=True, blank=True)
    q3_learning_in_public_score = models.FloatField(null=True, blank=True)

    min_time_spent_lectures = models.FloatField(null=True, blank=True)
    max_time_spent_lectures = models.FloatField(null=True, blank=True)
    avg_time_spent_lectures = models.FloatField(null=True, blank=True)
    median_time_spent_lectures = models.FloatField(null=True, blank=True)
    q1_time_spent_lectures = models.FloatField(null=True, blank=True)
    q3_time_spent_lectures = models.FloatField(null=True, blank=True)

    min_time_spent_homework = models.FloatField(null=True, blank=True)
    max_time_spent_homework = models.FloatField(null=True, blank=True)
    avg_time_spent_homework = models.FloatField(null=True, blank=True)
    median_time_spent_homework = models.FloatField(null=True, blank=True)
    q1_time_spent_homework = models.FloatField(null=True, blank=True)
    q3_time_spent_homework = models.FloatField(null=True, blank=True)

    last_calculated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Statistics for {self.homework.slug}"

    def get_value(self, field_name, stats_type):
        return getattr(self, f"{stats_type}_{field_name}")

    def get_stat_fields(self):
        return build_stat_fields(self, homework_stat_sections())


class ProjectState(Enum):
    CLOSED = "CL"
    COLLECTING_SUBMISSIONS = "CS"
    PEER_REVIEWING = "PR"
    COMPLETED = "CO"


PROJECT_STATE_CHOICES = [(state.value, state.name) for state in ProjectState]
PROJECT_STATE_LABELS = {
    ProjectState.CLOSED.value: "Closed",
    ProjectState.COLLECTING_SUBMISSIONS.value: "Collecting submissions",
    ProjectState.PEER_REVIEWING.value: "Peer reviewing",
    ProjectState.COMPLETED.value: "Completed",
}


class Project(models.Model):
    cohort = models.ForeignKey(Cohort, on_delete=models.CASCADE, related_name="projects")
    slug = models.SlugField(blank=False)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    instructions_url = models.URLField(  # noqa: DJ001 -- null means the link is unset.
        blank=True, null=True, validators=[URL_SCHEMES_WEB]
    )

    submission_due_date = models.DateTimeField()

    learning_in_public_cap_project = models.IntegerField(default=14)
    peer_review_due_date = models.DateTimeField()
    time_spent_project_field = models.BooleanField(default=True)

    problems_comments_field = models.BooleanField(default=True)
    faq_contribution_field = models.BooleanField(default=True)

    learning_in_public_cap_review = models.IntegerField(default=2)
    number_of_peers_to_evaluate = models.IntegerField(default=3)
    points_for_peer_review = models.IntegerField(default=3)
    time_spent_evaluation_field = models.BooleanField(default=True)

    state = models.CharField(max_length=2, choices=PROJECT_STATE_CHOICES, default="CS")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("cohort", "slug"), name="cb_project_cohort_slug_uq"),
        ]

    def __str__(self):
        return self.title

    def get_state_display(self):
        return PROJECT_STATE_LABELS.get(self.state, self.state)

    @property
    def points_to_pass(self):
        return self.cohort.project_passing_score

    def criteria_for_project(self):
        return criteria_for_project(self)

    def get_review_criteria(self):
        return self.criteria_for_project()


class ProjectSubmission(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_submissions"
    )
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="project_submissions"
    )

    github_link = models.URLField(validators=[URLValidator()])
    commit_id = models.CharField(max_length=40)

    learning_in_public_links = models.JSONField(blank=True, null=True)
    faq_contribution = models.TextField(blank=True)
    faq_contribution_url = models.URLField(  # noqa: DJ001 -- null means the link is unset.
        blank=True, null=True
    )

    time_spent = models.FloatField(blank=True, null=True)
    problems_comments = models.TextField(blank=True)

    submitted_at = models.DateTimeField(default=timezone.now)

    project_score = models.IntegerField(default=0)
    project_faq_score = models.IntegerField(default=0)
    project_learning_in_public_score = models.IntegerField(default=0)

    peer_review_score = models.IntegerField(default=0)
    peer_review_learning_in_public_score = models.IntegerField(default=0)

    total_score = models.IntegerField(default=0)

    reviewed_enough_peers = models.BooleanField(default=False)
    passed = models.BooleanField(default=False)
    volunteer_review_only = models.BooleanField(default=False)

    def __str__(self):
        return f"project submission for enrollment {self.enrollment_id}"


class ProjectVote(models.Model):
    submission = models.ForeignKey(
        ProjectSubmission, on_delete=models.CASCADE, related_name="votes"
    )
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_votes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("submission", "voter"), name="cb_project_vote_submission_voter_uq"
            )
        ]

    def __str__(self):
        return f"vote by user {self.voter_id} for project submission {self.submission_id}"


class ReviewCriteriaTypes(Enum):
    RADIO_BUTTONS = "RB"
    CHECKBOXES = "CB"


REVIEW_CRITERIA_TYPES = (
    (ReviewCriteriaTypes.RADIO_BUTTONS.value, "Radio Buttons"),
    (ReviewCriteriaTypes.CHECKBOXES.value, "Checkboxes"),
)


class ReviewCriteria(models.Model):
    """An independent criterion definition used through project assignments.

    ``cohort`` is retained as nullable, deprecated provenance for rows created
    by the legacy cohort-wide rubric. New integrations must use
    :class:`ProjectCriteriaAssignment`; this field is not the operational
    ownership boundary and may be empty for newly defined criteria.
    """

    cohort = models.ForeignKey(
        Cohort,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_criteria",
        help_text=("Deprecated legacy cohort provenance; use project criteria assignments."),
    )
    description = models.CharField(max_length=255)
    options = models.JSONField(validators=[validate_review_criteria_options])
    review_criteria_type = models.CharField(max_length=2, choices=REVIEW_CRITERIA_TYPES)

    def __str__(self):
        return self.description

    def median_score(self) -> int:
        result = 0
        scores = [option["score"] for option in self.options]

        if self.review_criteria_type == ReviewCriteriaTypes.RADIO_BUTTONS.value:
            result = statistics.median(scores)

        if self.review_criteria_type == ReviewCriteriaTypes.CHECKBOXES.value:
            result = sum(scores) / 2

        return math.ceil(result)

    @classmethod
    def for_project(cls, project):
        return criteria_for_project(project)


class ProjectCriteriaAssignment(models.Model):
    """An ordered assignment of one criterion definition to one project."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="criteria_assignments"
    )
    criteria = models.ForeignKey(
        ReviewCriteria, on_delete=models.PROTECT, related_name="project_assignments"
    )
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "position"),
                name="cb_project_criteria_position_uq",
            ),
            models.UniqueConstraint(
                fields=("project", "criteria"),
                name="cb_project_criteria_definition_uq",
            ),
        ]

    def __str__(self):
        return f"{self.project}: {self.criteria}"

    def clean(self):
        super().clean()
        if not self.project_id or not self.criteria_id:
            return

        project = self.project
        criteria = self.criteria
        errors = {}

        if criteria.cohort_id is not None and criteria.cohort_id != project.cohort_id:
            errors["criteria"] = (
                "A criterion's deprecated cohort provenance must match the project cohort."
            )

        other_assignments = type(self).objects.filter(criteria_id=self.criteria_id)
        if self.pk:
            other_assignments = other_assignments.exclude(pk=self.pk)
        if other_assignments.exclude(project__cohort_id=project.cohort_id).exists():
            errors["criteria"] = "A criterion can only be assigned to projects in one cohort."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def for_project(cls, project):
        return cls.objects.filter(project=project).order_by("position", "id")

    @property
    def criterion(self):
        return self.criteria

    @property
    def review_criteria(self):
        return self.criteria


def criteria_for_project(project):
    """Return the ordered rubric for one project.

    Module cohorts are strict: only explicit ProjectCriteriaAssignment rows
    are accepted. Legacy cohorts retain a narrow compatibility adapter for
    fixtures and rows created before the backfill.
    """

    if not getattr(project, "pk", None):
        return ReviewCriteria.objects.none()

    assigned = ReviewCriteria.objects.filter(
        project_assignments__project_id=project.pk,
    ).order_by(
        "project_assignments__position",
        "project_assignments__id",
    )
    if assigned.exists():
        return assigned

    if getattr(project.cohort, "curriculum_format", "legacy") != "legacy":
        return assigned

    return ReviewCriteria.objects.filter(
        cohort_id=project.cohort_id,
    ).order_by("id")


class PeerReviewState(Enum):
    TO_REVIEW = "TR"
    SUBMITTED = "SU"


PEER_REVIEW_STATE_CHOICES = [(state.value, state.name) for state in PeerReviewState]
PEER_REVIEW_STATE_LABELS = {
    PeerReviewState.TO_REVIEW.value: "To review",
    PeerReviewState.SUBMITTED.value: "Submitted",
}


class PeerReview(models.Model):
    submission_under_evaluation = models.ForeignKey(
        ProjectSubmission, related_name="reviews_under_evaluation", on_delete=models.CASCADE
    )
    reviewer = models.ForeignKey(
        ProjectSubmission, related_name="reviewers", on_delete=models.CASCADE
    )
    note_to_peer = models.TextField()
    learning_in_public_links = models.JSONField(blank=True, null=True)
    time_spent_reviewing = models.FloatField(blank=True, null=True)
    problems_comments = models.TextField(blank=True)

    optional = models.BooleanField(default=False, null=False, blank=False)

    submitted_at = models.DateTimeField(null=True, blank=True)

    state = models.CharField(max_length=2, choices=PEER_REVIEW_STATE_CHOICES, default="TR")

    def __str__(self):
        return f"Peer review {self.id}, state={self.state}"

    def get_state_display(self):
        return PEER_REVIEW_STATE_LABELS.get(self.state, self.state)


class CriteriaResponse(models.Model):
    review = models.ForeignKey(
        PeerReview, related_name="criteria_responses", on_delete=models.CASCADE
    )
    criteria = models.ForeignKey(ReviewCriteria, on_delete=models.PROTECT)
    answer = models.CharField(  # noqa: DJ001 -- null means the question was skipped.
        max_length=255, blank=True, null=True
    )

    def __str__(self):
        return f"{self.criteria.description}: {self.answer}"

    def get_scores(self):
        criteria = self.criteria

        if not self.answer:
            return [0]

        scores = []
        for answer in self.answer.split(","):
            option = criteria.options[int(answer) - 1]
            scores.append(option["score"])
        return scores

    def get_score(self):
        return sum(self.get_scores())


class ProjectEvaluationScore(models.Model):
    submission = models.ForeignKey(ProjectSubmission, on_delete=models.CASCADE)
    review_criteria = models.ForeignKey(ReviewCriteria, on_delete=models.PROTECT)
    score = models.IntegerField()

    def __str__(self):
        return f"Score: {self.score} for submission by {self.submission.id}"


class ProjectStatistics(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="statistics")

    total_submissions = models.IntegerField(default=0)

    min_project_score = models.IntegerField(null=True, blank=True)
    max_project_score = models.IntegerField(null=True, blank=True)
    avg_project_score = models.FloatField(null=True, blank=True)
    median_project_score = models.FloatField(null=True, blank=True)
    q1_project_score = models.FloatField(null=True, blank=True)
    q3_project_score = models.FloatField(null=True, blank=True)

    min_project_learning_in_public_score = models.IntegerField(null=True, blank=True)
    max_project_learning_in_public_score = models.IntegerField(null=True, blank=True)
    avg_project_learning_in_public_score = models.FloatField(null=True, blank=True)
    median_project_learning_in_public_score = models.FloatField(null=True, blank=True)
    q1_project_learning_in_public_score = models.FloatField(null=True, blank=True)
    q3_project_learning_in_public_score = models.FloatField(null=True, blank=True)

    min_peer_review_score = models.IntegerField(null=True, blank=True)
    max_peer_review_score = models.IntegerField(null=True, blank=True)
    avg_peer_review_score = models.FloatField(null=True, blank=True)
    median_peer_review_score = models.FloatField(null=True, blank=True)
    q1_peer_review_score = models.FloatField(null=True, blank=True)
    q3_peer_review_score = models.FloatField(null=True, blank=True)

    min_peer_review_learning_in_public_score = models.IntegerField(null=True, blank=True)
    max_peer_review_learning_in_public_score = models.IntegerField(null=True, blank=True)
    avg_peer_review_learning_in_public_score = models.FloatField(null=True, blank=True)
    median_peer_review_learning_in_public_score = models.FloatField(null=True, blank=True)
    q1_peer_review_learning_in_public_score = models.FloatField(null=True, blank=True)
    q3_peer_review_learning_in_public_score = models.FloatField(null=True, blank=True)

    min_total_score = models.IntegerField(null=True, blank=True)
    max_total_score = models.IntegerField(null=True, blank=True)
    avg_total_score = models.FloatField(null=True, blank=True)
    median_total_score = models.FloatField(null=True, blank=True)
    q1_total_score = models.FloatField(null=True, blank=True)
    q3_total_score = models.FloatField(null=True, blank=True)

    min_time_spent = models.FloatField(null=True, blank=True)
    max_time_spent = models.FloatField(null=True, blank=True)
    avg_time_spent = models.FloatField(null=True, blank=True)
    median_time_spent = models.FloatField(null=True, blank=True)
    q1_time_spent = models.FloatField(null=True, blank=True)
    q3_time_spent = models.FloatField(null=True, blank=True)

    last_calculated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Statistics for {self.project.slug}"

    def get_value(self, field_name, stats_type):
        return getattr(self, f"{stats_type}_{field_name}")

    def get_stat_fields(self):
        return build_stat_fields(self, project_stat_sections())


class LeaderboardComplaint(models.Model):
    class IssueType(models.TextChoices):
        LEARNING_IN_PUBLIC = "learning_in_public", "Incorrect learning in public links"
        HOMEWORK = "homework", "Incorrect homework"
        PROJECT = "project", "Incorrect project"
        OTHER = "other", "Other leaderboard issue"

    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="complaints")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leaderboard_complaints",
    )
    issue_type = models.CharField(max_length=32, choices=IssueType.choices)
    description = models.TextField()
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_leaderboard_complaints",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["resolved", "-created_at"]

    def __str__(self):
        return f"{self.get_issue_type_display()} for {self.enrollment.display_name}"


class RegistrationCampaign(models.Model):
    """A reusable registration campaign promoting one cohort."""

    slug = models.SlugField(unique=True, blank=False)
    title = models.CharField(max_length=200)
    edition_label = models.CharField(
        max_length=200, blank=True, help_text="Displayed cohort label, for example '2026 cohort'."
    )
    current_cohort = models.ForeignKey(
        Cohort,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registration_campaigns",
        help_text="Cohort currently promoted by this form.",
    )
    is_active = models.BooleanField(default=True)

    registration_baseline_cohort = models.ForeignKey(
        Cohort,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text=(
            "The cohort the baseline count was recorded for. It stops applying the moment "
            "the campaign promotes a different cohort."
        ),
    )
    registration_baseline_count = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Registrations that happened before this campaign's CourseRegistration rows "
            "existed. Zero for a campaign whose registrations are all native rows."
        ),
    )
    registration_native_start_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When native CourseRegistration rows became the complete record for this "
            "campaign. Only registrations at or after this instant are added to the baseline."
        ),
    )

    marketing_markdown = models.TextField(blank=True)
    meta_description = models.TextField(blank=True)
    hero_image_url = models.URLField(blank=True, validators=[URL_SCHEMES_WEB])
    video_url = models.URLField(blank=True, validators=[URL_SCHEMES_WEB])

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title", "slug"]

    def __str__(self):
        return self.title


class CourseRegistration(models.Model):
    """One registration snapshot for a campaign and cohort."""

    class Role(models.TextChoices):
        DATA_ENGINEER = "data_engineer", "Data Engineer"
        DATA_SCIENTIST = "data_scientist", "Data Scientist"
        DATA_ANALYST = "data_analyst", "Data Analyst"
        ML_ENGINEER = "ml_engineer", "ML Engineer"
        SOFTWARE_ENGINEER_BACKEND = "software_engineer_backend", "Software Engineer (Backend)"
        SOFTWARE_ENGINEER_OTHER = (
            "software_engineer_other",
            "Software Engineer (Frontend, Test, etc)",
        )
        STUDENT_STEM = "student_stem", "Student (STEM)"
        STUDENT_NON_STEM = "student_non_stem", "Student (Non-STEM)"
        OTHER = "other", "Other"

    campaign = models.ForeignKey(
        RegistrationCampaign, on_delete=models.CASCADE, related_name="registrations"
    )
    cohort = models.ForeignKey(
        Cohort, on_delete=models.SET_NULL, null=True, blank=True, related_name="registrations"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="course_registrations",
    )

    email = models.EmailField()
    email_normalized = models.EmailField(editable=False)
    name = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=100)
    region = models.CharField(max_length=100)
    role = models.CharField(max_length=40, choices=Role.choices)
    comment = models.TextField(blank=True)
    accepted_newsletter = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "email_normalized"),
                name="cb_course_registration_campaign_email_uq",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email_normalized} registered for {self.campaign}"

    def save(self, *args, **kwargs):
        self.email_normalized = (self.email or "").strip().lower()
        if self.campaign_id and self.cohort_id is None:
            self.cohort = self.campaign.current_cohort
        super().save(*args, **kwargs)


class TestimonialPlacement(models.TextChoices):
    HOMEPAGE = "homepage", "Homepage"
    COURSE = "course", "Course family"


ASSET_KEY_PATTERN = r"^(?!/)(?!.*\.\.)(?!.*\\)(?!\w+:)[\w.-]+(?:/[\w.-]+)*$"


class Testimonial(models.Model):
    """One member quote, scoped to a placement: homepage or one course family."""

    placement = models.CharField(
        max_length=16,
        choices=TestimonialPlacement.choices,
        help_text="Homepage testimonials carry no course; course testimonials carry exactly one.",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="course_testimonials",
        help_text="The course family this testimonial belongs to. Empty for the homepage.",
    )
    name = models.CharField(max_length=200)
    attribution = models.CharField(max_length=200, blank=True)
    quote = models.TextField()
    source_url = models.URLField(max_length=500, blank=True)
    portrait_asset_key = models.CharField(
        max_length=200,
        blank=True,
        validators=[
            RegexValidator(ASSET_KEY_PATTERN, "Enter a key relative to the site-assets prefix.")
        ],
    )
    role_before = models.CharField(max_length=120, blank=True)
    role_after = models.CharField(max_length=120, blank=True)
    elapsed = models.CharField(max_length=60, blank=True)
    position = models.PositiveIntegerField(default=0)
    published = models.BooleanField(default=False)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(placement=TestimonialPlacement.HOMEPAGE, course__isnull=True)
                    | Q(placement=TestimonialPlacement.COURSE, course__isnull=False)
                ),
                name="cb_testimonial_placement_scope",
            ),
        ]
        indexes = [
            models.Index(
                fields=("placement", "published", "position"),
                name="cb_testimonial_read_idx",
            ),
        ]

    def __str__(self) -> str:
        scope = self.course.title if self.course_id else "homepage"
        return f"{self.name} ({scope})"

    def clean(self) -> None:
        super().clean()
        if self.placement == TestimonialPlacement.HOMEPAGE and self.course_id is not None:
            raise ValidationError({"course": "A homepage testimonial cannot name a course."})
        if self.placement == TestimonialPlacement.COURSE and self.course_id is None:
            raise ValidationError({"course": "A course testimonial must name a course."})


class WrappedStatistics(models.Model):
    """Pre-calculated platform statistics for a Wrapped edition."""

    year = models.IntegerField(unique=True)
    is_visible = models.BooleanField(default=False)

    total_participants = models.IntegerField(default=0)
    total_enrollments = models.IntegerField(default=0)
    total_hours = models.FloatField(default=0)
    total_certificates = models.IntegerField(default=0)
    total_points = models.IntegerField(default=0)

    course_stats = models.JSONField(default=list)
    leaderboard = models.JSONField(default=list)

    calculated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        visibility_label = "Visible" if self.is_visible else "Hidden"
        return f"Wrapped {self.year} ({visibility_label})"


class UserWrappedStatistics(models.Model):
    """Pre-calculated statistics for one user's wrapped page."""

    wrapped = models.ForeignKey(
        WrappedStatistics, on_delete=models.CASCADE, related_name="user_statistics"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wrapped_statistics"
    )

    total_points = models.IntegerField(default=0)
    total_hours = models.FloatField(default=0)
    homework_count = models.IntegerField(default=0)
    project_count = models.IntegerField(default=0)
    peer_reviews_given = models.IntegerField(default=0)
    learning_in_public_count = models.IntegerField(default=0)
    faq_contributions_count = models.IntegerField(default=0)
    certificates_earned = models.IntegerField(default=0)

    courses = models.JSONField(default=list)

    rank = models.IntegerField(null=True, blank=True)
    display_name = models.CharField(max_length=200, blank=True)

    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("wrapped", "user"), name="cb_user_wrapped_wrapped_user_uq"
            )
        ]
        ordering = ["rank"]

    def __str__(self):
        return f"{self.display_name} - Wrapped {self.wrapped.year}"
