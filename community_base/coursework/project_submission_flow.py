"""Build and process the shared project submission form from a host view (C5.2n).

The host resolves the project and enrollment through its own access rules, then calls
``build_project_submission_form`` for a GET and ``process_project_submission`` for a POST.
Neither adds messages or redirects; the host turns ``ProjectSubmissionOutcome`` into a response.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from community_base.coursework.hooks import hooks as coursework_hooks
from community_base.coursework.models import ProjectSubmission
from community_base.coursework.project_form_fields import CLOSED_MESSAGE
from community_base.coursework.project_forms import ProjectSubmissionForm
from community_base.coursework.projects import delete_project_submission, learner_submission_for

DELETE_ACTION = "delete"


@dataclass
class ProjectSubmissionOutcome:
    """What ``process_project_submission`` did. The host turns it into messages and a response.

    ``action`` is one of ``"saved"``, ``"deleted"``, ``"invalid"``, ``"closed"`` or
    ``"anonymous"``. ``form`` is ready to render again (``"invalid"`` and ``"closed"`` keep the
    posted values and errors).
    """

    action: str
    form: ProjectSubmissionForm
    submission: ProjectSubmission | None = None
    created: bool = False

    @property
    def succeeded(self) -> bool:
        return self.action in {"saved", "deleted"}


def build_project_submission_form(
    project,
    *,
    user,
    enrollment=None,
    data=None,
    form_class: type[ProjectSubmissionForm] = ProjectSubmissionForm,
    **form_kwargs,
) -> ProjectSubmissionForm:
    """The form for ``user``'s own submission, for a GET or to re-render after a POST."""

    submission = None
    if user is not None and user.is_authenticated:
        submission = learner_submission_for(project, user)
    return form_class(
        data,
        project=project,
        submission=submission,
        enrollment=enrollment,
        user=user,
        **form_kwargs,
    )


def process_project_submission(
    request,
    project,
    enrollment,
    *,
    form_class: type[ProjectSubmissionForm] = ProjectSubmissionForm,
    **form_kwargs,
) -> ProjectSubmissionOutcome:
    """Handle a POST of the shared form: save, remove, or report why not.

    The host resolves ``project`` and ``enrollment`` through its own access rules, then calls
    this from its view. It does not add messages or redirect. After a successful save or delete
    it fires ``COURSEWORK_PROJECT_SUBMITTED`` (``submission``, ``created``) or
    ``COURSEWORK_PROJECT_DELETED`` (``project``, ``user``) once the transaction commits.
    """

    user = request.user
    form = build_project_submission_form(
        project,
        user=user,
        enrollment=enrollment,
        data=request.POST,
        form_class=form_class,
        **form_kwargs,
    )
    if not form.is_authenticated:
        return ProjectSubmissionOutcome("anonymous", form)
    if not form.editable:
        form.add_error(None, CLOSED_MESSAGE)
        return ProjectSubmissionOutcome("closed", form, form.submission)

    if request.POST.get("action") == DELETE_ACTION:
        if delete_project_submission(project, user):
            transaction.on_commit(
                lambda: coursework_hooks.project_deleted(project=project, user=user)
            )
        blank = build_project_submission_form(
            project, user=user, enrollment=enrollment, form_class=form_class, **form_kwargs
        )
        return ProjectSubmissionOutcome("deleted", blank)

    if not form.is_valid():
        return ProjectSubmissionOutcome("invalid", form, form.submission)
    try:
        submission, created = form.save()
    except ValidationError as error:
        form.add_model_errors(error)
        return ProjectSubmissionOutcome("invalid", form, form.submission)
    transaction.on_commit(
        lambda: coursework_hooks.project_submitted(submission=submission, created=created)
    )
    return ProjectSubmissionOutcome("saved", form, submission, created)
