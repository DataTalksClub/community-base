"""The shared, embeddable project submission form (C5.2n).

One form for CMP, DataTalks.Club and AI Shipping Labs. It ports CMP's "Submission details"
(``courses/templates/projects/project.html`` and ``courses/views/project_submission_edit.py``):

- GitHub link to the project (required);
- commit id, when the project's ``commit_id_field`` is on;
- learning in public links, up to ``learning_in_public_cap_project``;
- time spent on the project in hours, when ``time_spent_project_field`` is on;
- certificate name, behind ``COMMUNITY_BASE["COURSEWORK_PROJECT_CERTIFICATE_NAME_FIELD"]`` or the
  ``certificate_name_field`` argument;
- a status line with save-now, update-before-the-deadline semantics.

A host site embeds ``coursework/_project_submission_form.html`` with ``project_form`` in the
context and calls ``project_submission_flow.process_project_submission`` from its own view.
Extension point: subclass ``ProjectSubmissionForm``, declare extra fields, and write them in
``apply_extra_fields``; the partial renders every extra field, or includes
``extra_fields_template`` when the subclass sets one. DataTalks.Club adds its FAQ contribution
field this way. The package form never renders the ``faq_*`` columns; it only preserves their
stored values.
"""

from urllib.parse import urlsplit

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from community_base.coursework.models import ProjectSubmission
from community_base.coursework.project_form_fields import (
    CERTIFICATE_NAME_HELP,
    CLOSED_MESSAGE,
    COMMIT_ID_HELP,
    COMMIT_ID_PATTERN,
    GITHUB_LINK_HELP,
    LEARNING_IN_PUBLIC_HELP,
    TIME_SPENT_HELP,
    LearningInPublicLinksField,
    certificate_name_field_enabled,
)
from community_base.coursework.projects import (
    WEB_LINK_VALIDATOR,
    project_accepts_submissions,
    submission_editable,
    submit_project,
)


class ProjectSubmissionForm(forms.Form):
    """The learner's project submission, shaped by the project's field toggles.

    Keyword arguments:

    - ``project`` (required) and ``submission`` (the learner's current one, or ``None``);
    - ``enrollment``: required to save; its ``disable_learning_in_public`` hides the links;
    - ``user``: the viewer; anonymous viewers get a read-only preview;
    - ``certificate_name_field``: ``True``/``False`` overrides the site setting for this form,
      so a host can decide per course;
    - ``action_url``: where the partial posts (empty posts to the current page);
    - ``now``: the clock, for the deadline lock.

    Subclass hooks: ``github_hosts`` (``None`` accepts any public http(s) link),
    ``extra_fields_template`` and ``apply_extra_fields``.
    """

    # Hosts accepted for the repository link. ``None`` accepts any public http(s) URL.
    github_hosts: tuple[str, ...] | None = ("github.com", "www.github.com")
    # Optional template for the fields a subclass adds; ``None`` renders them generically.
    extra_fields_template: str | None = None
    # Optional screenshot for the "Where do I find the commit ID?" disclosure.
    commit_id_help_image_url: str = ""

    github_link = forms.CharField(
        label="GitHub link to the project",
        max_length=200,
        help_text=GITHUB_LINK_HELP,
        widget=forms.URLInput(
            attrs={"class": "cb-input", "inputmode": "url", "autocomplete": "url"}
        ),
    )
    commit_id = forms.CharField(
        label="Commit ID",
        required=False,
        max_length=40,
        help_text=COMMIT_ID_HELP,
        widget=forms.TextInput(
            attrs={"class": "cb-input", "autocomplete": "off", "spellcheck": "false"}
        ),
    )
    time_spent = forms.FloatField(
        label="Time spent on project (hours)",
        required=False,
        min_value=0,
        help_text=TIME_SPENT_HELP,
        widget=forms.NumberInput(attrs={"class": "cb-input", "step": "any"}),
    )
    # Optional on the server, as in CMP: a blank value keeps the enrollment's current name.
    certificate_name = forms.CharField(
        label="Certificate name",
        required=False,
        max_length=255,
        help_text=CERTIFICATE_NAME_HELP,
        widget=forms.TextInput(attrs={"class": "cb-input", "autocomplete": "name"}),
    )

    CORE_FIELDS = (
        "github_link",
        "commit_id",
        "learning_in_public_links",
        "time_spent",
        "certificate_name",
    )

    def __init__(
        self,
        data=None,
        *,
        project,
        submission: ProjectSubmission | None = None,
        enrollment=None,
        user=None,
        certificate_name_field: bool | None = None,
        action_url: str = "",
        now=None,
        **kwargs,
    ):
        self.project = project
        self.submission = submission
        self.enrollment = enrollment
        self.user = user
        self.action_url = action_url
        self.is_authenticated = bool(user is not None and user.is_authenticated)
        self.accepting_submissions = project_accepts_submissions(project, now)
        self.editable = self.is_authenticated and submission_editable(project, submission, now)
        if certificate_name_field is None:
            certificate_name_field = certificate_name_field_enabled()
        kwargs.setdefault("initial", self._initial_from(submission, enrollment))
        super().__init__(data, **kwargs)
        self._apply_project_toggles(certificate_name_field)
        if not self.editable:
            for field in self.fields.values():
                field.disabled = True

    def _initial_from(self, submission, enrollment) -> dict:
        initial = {}
        if submission is not None:
            initial = {
                "github_link": submission.github_link,
                "commit_id": submission.commit_id,
                "learning_in_public_links": list(submission.learning_in_public_links or []),
                "time_spent": submission.time_spent,
            }
        if enrollment is not None:
            initial["certificate_name"] = enrollment.certificate_name or enrollment.display_name
        return initial

    def _apply_project_toggles(self, certificate_name_field: bool) -> None:
        project = self.project
        if project.commit_id_field:
            self.fields["commit_id"].required = True
        else:
            del self.fields["commit_id"]
        if project.learning_in_public_cap_project > 0 and not self.learning_in_public_disabled:
            self.fields["learning_in_public_links"] = LearningInPublicLinksField(
                cap=project.learning_in_public_cap_project,
                label="Learning in public links",
                help_text=LEARNING_IN_PUBLIC_HELP,
            )
        if not project.time_spent_project_field:
            del self.fields["time_spent"]
        if not certificate_name_field:
            del self.fields["certificate_name"]

    @property
    def learning_in_public_disabled(self) -> bool:
        return bool(self.enrollment is not None and self.enrollment.disable_learning_in_public)

    # Rendering helpers used by the partial.

    @property
    def has_submission(self) -> bool:
        return self.submission is not None

    @property
    def learning_in_public_cap(self) -> int:
        return self.project.learning_in_public_cap_project

    @property
    def learning_in_public_values(self) -> list[str]:
        """The links to prefill: what was posted on a re-render, else what is saved."""

        if "learning_in_public_links" not in self.fields:
            return []
        if self.is_bound and not self.fields["learning_in_public_links"].disabled:
            values = self["learning_in_public_links"].value() or []
        else:
            values = self.initial.get("learning_in_public_links") or []
        return [value for value in values if value][: self.learning_in_public_cap]

    @property
    def learning_in_public_blank_slot(self) -> bool:
        return self.editable and len(self.learning_in_public_values) < self.learning_in_public_cap

    def extra_fields(self) -> list:
        """Bound fields a subclass added, in declaration order."""

        return [self[name] for name in self.fields if name not in self.CORE_FIELDS]

    # Validation.

    def clean_github_link(self):
        link = (self.cleaned_data.get("github_link") or "").strip()
        try:
            WEB_LINK_VALIDATOR(link)
        except ValidationError:
            raise ValidationError("Enter a valid http or https link.") from None
        if self.github_hosts is None:
            return link
        parts = urlsplit(link)
        path = [part for part in parts.path.split("/") if part]
        if (parts.hostname or "").lower() not in self.github_hosts or len(path) < 2:
            raise ValidationError(
                "Enter a GitHub repository link, for example https://github.com/owner/repo."
            )
        return link

    def clean_commit_id(self):
        commit_id = (self.cleaned_data.get("commit_id") or "").strip()
        if commit_id and not COMMIT_ID_PATTERN.match(commit_id):
            raise ValidationError(
                "Enter a commit ID: 7 to 40 hexadecimal characters, for example a1b2c3d."
            )
        return commit_id

    def clean_certificate_name(self):
        return (self.cleaned_data.get("certificate_name") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        if not self.editable:
            raise ValidationError(CLOSED_MESSAGE, code="closed")
        return cleaned_data

    # Saving.

    def apply_extra_fields(self, submission: ProjectSubmission) -> None:
        """Write the fields a subclass added onto ``submission`` before it is validated.

        Runs inside ``submit_project``'s transaction, after the package fields are set and before
        ``full_clean``, so a model ``ValidationError`` here is reported on the form.
        """

    def save(self) -> tuple[ProjectSubmission, bool]:
        """Create or update the submission. Call only after ``is_valid()``."""

        if self.enrollment is None:
            raise ValueError("Saving a project submission needs the learner's enrollment.")
        data = self.cleaned_data
        existing = self.submission
        with transaction.atomic():
            submission, created = submit_project(
                self.project,
                self.enrollment,
                github_link=data["github_link"],
                commit_id=data.get("commit_id", ""),
                learning_in_public_links=data.get("learning_in_public_links") or [],
                time_spent=data.get("time_spent"),
                # The shared form does not show these; keep what is stored (C5.2n).
                problems_comments=existing.problems_comments if existing else "",
                faq_contribution_url=(existing.faq_contribution_url or "") if existing else "",
                before_save=self.apply_extra_fields,
            )
            certificate_name = data.get("certificate_name", "")
            if certificate_name and certificate_name != self.enrollment.certificate_name:
                self.enrollment.certificate_name = certificate_name
                self.enrollment.save(update_fields=["certificate_name"])
        self.submission = submission
        return submission, created

    def add_model_errors(self, error: ValidationError) -> None:
        """Report a model ``ValidationError`` on the matching field, else as a form error."""

        if not hasattr(error, "error_dict"):
            self.add_error(None, error)
            return
        for field, messages in error.message_dict.items():
            self.add_error(field if field in self.fields else None, messages)
