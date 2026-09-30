"""C5.2m: the coursework knobs a site needs to adopt projects without the package surfaces.

- `Project.module` places a project in a cohort module, like `Homework.module`.
- `Project.commit_id_field` makes the commit id optional for a site that collects only the
  repository link.
- `COURSEWORK_STUDIO_ENABLED` and `COURSEWORK_MEMBER_API_ENABLED` let a site install the app
  with no package Studio section and no member API routes.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.urls import include, path, reverse

from community_base.accounts.models import User
from community_base.coursework.models import ProjectSubmission
from community_base.coursework.projects import submit_project
from community_base.curriculum.models import Module
from tests.coursework.test_models import coursework_cohort, enrollment_for
from tests.coursework.test_projects import make_project

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_LINK = "https://github.com/example/repo"

urlpatterns = [path("courses/", include("community_base.coursework.urls"))]


@pytest.fixture
def coursework_urlconf(settings):
    settings.ROOT_URLCONF = __name__


@pytest.mark.django_db
def test_project_keeps_existing_when_its_module_is_deleted():
    cohort = coursework_cohort()
    module = Module.objects.create(course=cohort.course, slug="week-1", title="Week 1")
    project = make_project(cohort, module=module)

    assert list(module.projects.all()) == [project]

    module.delete()
    project.refresh_from_db()

    assert project.module is None


@pytest.mark.django_db
def test_commit_id_is_required_by_default():
    cohort = coursework_cohort()
    project = make_project(cohort)
    _user, enrollment = enrollment_for(cohort)

    with pytest.raises(ValidationError) as raised:
        submit_project(project, enrollment, github_link=REPO_LINK, commit_id="")

    assert "commit_id" in raised.value.message_dict
    assert ProjectSubmission.objects.count() == 0


@pytest.mark.django_db
def test_commit_id_is_optional_when_the_project_turns_it_off():
    cohort = coursework_cohort()
    project = make_project(cohort, commit_id_field=False)
    _user, enrollment = enrollment_for(cohort)

    submission, created = submit_project(project, enrollment, github_link=REPO_LINK)

    assert created is True
    submission.refresh_from_db()
    assert submission.github_link == REPO_LINK
    assert submission.commit_id == ""


@pytest.mark.django_db
def test_a_commit_id_is_not_stored_when_the_project_turns_it_off():
    cohort = coursework_cohort()
    project = make_project(cohort, commit_id_field=False)
    _user, enrollment = enrollment_for(cohort)

    submission, _created = submit_project(
        project, enrollment, github_link=REPO_LINK, commit_id="a" * 40
    )

    submission.refresh_from_db()
    assert submission.commit_id == ""


@pytest.mark.django_db
def test_full_clean_requires_commit_id_only_when_the_project_asks_for_it():
    cohort = coursework_cohort()
    _user, enrollment = enrollment_for(cohort)
    required = make_project(cohort, slug="required")
    optional = make_project(cohort, slug="optional", commit_id_field=False)

    blank_for_required = ProjectSubmission(
        project=required, student=enrollment.user, enrollment=enrollment, github_link=REPO_LINK
    )
    with pytest.raises(ValidationError) as raised:
        blank_for_required.full_clean()
    assert list(raised.value.message_dict) == ["commit_id"]

    ProjectSubmission(
        project=optional, student=enrollment.user, enrollment=enrollment, github_link=REPO_LINK
    ).full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize(("commit_id_field", "shows_input"), [(True, True), (False, False)])
def test_project_page_shows_the_commit_id_input_only_when_asked(
    client, coursework_urlconf, commit_id_field, shows_input
):
    project = make_project(coursework_cohort(), commit_id_field=commit_id_field)
    client.force_login(User.objects.create_user(email="page-viewer@example.com"))

    response = client.get(reverse("coursework_project", args=["cw-course", "cw", project.slug]))

    assert response.status_code == 200
    assert ('name="commit_id"' in response.content.decode()) is shows_input


@pytest.mark.django_db
def test_project_view_saves_a_link_only_submission(client, coursework_urlconf):
    project = make_project(coursework_cohort(), commit_id_field=False)
    user = User.objects.create_user(email="link-only@example.com")
    client.force_login(user)

    response = client.post(
        reverse("coursework_project", args=["cw-course", "cw", project.slug]),
        {"github_link": REPO_LINK},
    )

    assert response.status_code == 302
    assert ProjectSubmission.objects.get(project=project, student=user).commit_id == ""


BOOT_WITH_SURFACE_SETTINGS = """
import sys

import django
from django.conf import settings

enabled = sys.argv[1] == "on"
community_base = {}
if sys.argv[1] != "default":
    community_base = {
        "COURSEWORK_STUDIO_ENABLED": enabled,
        "COURSEWORK_MEMBER_API_ENABLED": enabled,
    }
settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "community_base.kernel",
        "community_base.config",
        "community_base.api",
        "community_base.studio",
        "community_base.jobs",
        "community_base.mail",
        "community_base.events",
        "community_base.curriculum",
        "community_base.coursework",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    COMMUNITY_BASE=community_base,
)
django.setup()

from community_base.api.registry import routes
from community_base.studio.registry import sections

studio = [section.slug for section in sections() if section.slug == "coursework"]
api = [route.path for route in routes() if route.handler.__module__.startswith(
    "community_base.coursework"
)]
print(f"studio={len(studio)} api={len(api)}")
"""


def boot_surfaces(mode: str) -> str:
    """Boot a fresh process without `community_base.accounts` (the AISL shape)."""

    result = subprocess.run(
        [sys.executable, "-c", BOOT_WITH_SURFACE_SETTINGS, mode],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_surfaces_register_by_default():
    assert boot_surfaces("default") == "studio=1 api=3"


def test_surfaces_register_when_enabled_explicitly():
    assert boot_surfaces("on") == "studio=1 api=3"


def test_site_can_install_coursework_without_studio_or_member_api():
    assert boot_surfaces("off") == "studio=0 api=0"
