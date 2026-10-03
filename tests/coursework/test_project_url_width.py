"""C5.2q: validated project URL capacity and safe synthetic migration reversal."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from community_base.coursework.models import ProjectSubmission
from community_base.coursework.project_forms import ProjectSubmissionForm
from community_base.coursework.project_submission_flow import process_project_submission
from tests.coursework.project_form_support import COMMIT, post_request, render_form, valid_data
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import make_project

pytestmark = pytest.mark.django_db


class AnyHostForm(ProjectSubmissionForm):
    github_hosts = None


def repository_url(length, prefix="https://github.com/example/"):
    link = prefix + "r" * (length - len(prefix))
    assert len(link) == length
    return link


@pytest.fixture
def project_learner():
    cohort = coursework_cohort()
    user, enrollment = enrollment_for(cohort)
    return make_project(cohort), user, enrollment


def submission_for(project_learner, link):
    project, user, enrollment = project_learner
    return ProjectSubmission(
        project=project, student=user, enrollment=enrollment, github_link=link, commit_id=COMMIT
    )


def form_for(project_learner, link, form_class=ProjectSubmissionForm):
    project, user, enrollment = project_learner
    return form_class(
        project=project, user=user, enrollment=enrollment, data=valid_data(github_link=link)
    )


@pytest.mark.parametrize("length", [200, 201, 500])
def test_validated_model_preserves_exact_url(project_learner, length):
    link = repository_url(length)
    submission = submission_for(project_learner, link)
    submission.full_clean()
    submission.save()
    submission.refresh_from_db()

    assert submission.github_link == link
    project, user, enrollment = project_learner
    assert (submission.project_id, submission.student_id, submission.enrollment_id) == (
        project.pk,
        user.pk,
        enrollment.pk,
    )
    assert ProjectSubmission.objects.count() == 1


@pytest.mark.parametrize("length", [200, 201, 500])
def test_form_accepts_exact_valid_url(project_learner, length):
    link = repository_url(length)
    form = form_for(project_learner, link)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["github_link"] == link


def test_model_rejects_501_without_mutating_stored_row(project_learner):
    original = repository_url(200)
    submission = submission_for(project_learner, original)
    submission.full_clean()
    submission.save()
    submission.github_link = repository_url(501)

    with pytest.raises(ValidationError) as caught:
        submission.full_clean()
    assert list(caught.value.error_dict) == ["github_link"]
    assert caught.value.error_dict["github_link"][0].code == "max_length"
    submission.refresh_from_db()
    assert submission.github_link == original
    assert ProjectSubmission.objects.count() == 1


def test_form_rejects_501_without_mutating_stored_row(project_learner):
    project, user, enrollment = project_learner
    original = repository_url(200)
    submission = submission_for(project_learner, original)
    submission.save()
    outcome = process_project_submission(
        post_request(user, valid_data(github_link=repository_url(501))), project, enrollment
    )

    assert outcome.action == "invalid"
    assert list(outcome.form.errors) == ["github_link"]
    assert outcome.form.errors.as_data()["github_link"][0].code == "max_length"
    submission.refresh_from_db()
    assert submission.github_link == original
    assert ProjectSubmission.objects.count() == 1


def test_500_form_save_and_rendered_input_capacity(project_learner):
    link = repository_url(500)
    form = form_for(project_learner, link)
    assert form.is_valid(), form.errors
    submission, created = form.save()
    submission.refresh_from_db()

    assert created is True
    assert submission.github_link == link
    assert render_form(form).find("input", name="github_link", maxlength="500", value=link)


def test_500_non_github_url_requires_existing_host_override(project_learner):
    link = repository_url(500, prefix="https://gitlab.com/example/")
    default_form = form_for(project_learner, link)
    host_form = form_for(project_learner, link, AnyHostForm)

    assert not default_form.is_valid()
    assert list(default_form.errors) == ["github_link"]
    assert "GitHub repository" in default_form.errors["github_link"][0]
    assert host_form.is_valid(), host_form.errors
    assert host_form.cleaned_data["github_link"] == link


@pytest.mark.parametrize("link", ["not a url", "ftp://github.com/example/repo"])
def test_host_override_preserves_http_scheme_validation(project_learner, link):
    form = form_for(project_learner, link, AnyHostForm)

    assert not form.is_valid()
    assert list(form.errors) == ["github_link"]
    assert form.errors["github_link"] == ["Enter a valid http or https link."]


def test_model_keeps_existing_ftp_validator_semantics(project_learner):
    submission = submission_for(
        project_learner, repository_url(500, prefix="ftp://github.com/example/")
    )
    submission.full_clean()


def test_500_anonymous_post_does_not_write(project_learner):
    project, _user, _enrollment = project_learner
    outcome = process_project_submission(
        post_request(AnonymousUser(), valid_data(github_link=repository_url(500))), project, None
    )

    assert outcome.action == "anonymous"
    assert ProjectSubmission.objects.count() == 0


def test_500_closed_post_does_not_write(project_learner):
    project, user, enrollment = project_learner
    project.submission_due_date = timezone.now()
    project.save()
    outcome = process_project_submission(
        post_request(user, valid_data(github_link=repository_url(500))), project, enrollment
    )

    assert outcome.action == "closed"
    assert ProjectSubmission.objects.count() == 0


OLD_NODE = ("cb_coursework", "0006_project_module_commit_id_field")
NEW_NODE = ("cb_coursework", "0007_alter_projectsubmission_github_link")


@pytest.fixture
def migration_executor():
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    executor.migrate([OLD_NODE])
    try:
        yield executor
    finally:
        MigrationExecutor(connection).migrate(latest)


def migrated_submission_model(node, width):
    # Reload applied migrations after each transition; executor loaders cache that state.
    executor = MigrationExecutor(connection)
    executor.migrate([node])
    model = executor.loader.project_state([node]).apps.get_model(
        "cb_coursework", "ProjectSubmission"
    )
    assert model._meta.get_field("github_link").max_length == width
    # SQLite records varchar width but does not enforce it; validation is tested separately.
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute(f'PRAGMA table_info("{model._meta.db_table}")')
            columns = {}
            for column in cursor.fetchall():
                columns[column[1]] = column[2]
        assert columns["github_link"] == f"varchar({width})"
    return model


def original_rows(model):
    return list(model.objects.order_by("pk").values())


def check_synthetic_long_row(model, original, project_learner):
    project, user, enrollment = project_learner
    link = repository_url(500)
    synthetic = model(
        project_id=project.pk,
        student_id=user.pk,
        enrollment_id=enrollment.pk,
        github_link=link,
        commit_id=COMMIT,
    )
    synthetic.full_clean()
    synthetic.save()
    synthetic.refresh_from_db()
    assert synthetic.github_link == link
    assert model.objects.count() == len(original) + 1
    synthetic.delete()  # Only this synthetic long row is removed before narrowing.
    assert original_rows(model) == original


@pytest.mark.django_db(transaction=True)
def test_migration_preserves_original_rows_forward_reverse_reapply(
    project_learner, migration_executor
):
    old_model = migrated_submission_model(OLD_NODE, 200)
    project, user, enrollment = project_learner
    original = old_model(
        project_id=project.pk,
        student_id=user.pk,
        enrollment_id=enrollment.pk,
        github_link=repository_url(200),
        commit_id=COMMIT,
        problems_comments="Original description",
    )
    original.full_clean()
    original.save()
    snapshot = original_rows(old_model)
    assert len(snapshot) == 1
    new_model = migrated_submission_model(NEW_NODE, 500)
    assert original_rows(new_model) == snapshot
    check_synthetic_long_row(new_model, snapshot, project_learner)
    reversed_model = migrated_submission_model(OLD_NODE, 200)
    assert original_rows(reversed_model) == snapshot
    reapplied_model = migrated_submission_model(NEW_NODE, 500)
    assert original_rows(reapplied_model) == snapshot


def test_migration_changes_only_link_capacity():
    loader = MigrationExecutor(connection).loader
    migration = loader.get_migration(*NEW_NODE)
    assert migration.dependencies == [OLD_NODE]
    assert len(migration.operations) == 1
    operation = migration.operations[0]
    assert type(operation).__name__ == "AlterField"
    assert (operation.model_name, operation.name) == ("projectsubmission", "github_link")
    old_field = (
        loader.project_state([OLD_NODE])
        .apps.get_model("cb_coursework", "ProjectSubmission")
        ._meta.get_field("github_link")
    )
    old_settings = old_field.deconstruct()[3]
    new_settings = operation.field.deconstruct()[3]
    assert new_settings.pop("max_length") == 500
    old_settings.pop("max_length", None)
    assert new_settings == old_settings
