"""Execute instructor imports with a genuinely separate events model registry."""

import sys
from types import SimpleNamespace

import django
from django.conf import settings

settings.configure(
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "tests.curriculum.host_adapter.apps.SiteEventsConfig",
        "tests.curriculum.host_adapter.apps.ContentModelsConfig",
        "community_base.curriculum",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
)
django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402

from community_base.content_sync.models import ContentSource  # noqa: E402
from community_base.curriculum.importing import _sync_instructors  # noqa: E402
from community_base.curriculum.models import Course, CourseInstructor  # noqa: E402
from community_base.curriculum.source import InstructorGraph  # noqa: E402
from tests.curriculum.host_adapter.models import Host  # noqa: E402


def check_instructor_import(course):
    named = Host.objects.create(name="Ada", slug="ada", bio="Old")
    entries = (InstructorGraph("Grace", bio="First"), InstructorGraph("Ada", bio="Updated"))
    graph = SimpleNamespace(instructors=entries)
    _sync_instructors(course, graph)
    links = list(CourseInstructor.objects.order_by("position"))
    assert [link.host.name for link in links] == ["Grace", "Ada"]
    assert [link.position for link in links] == [0, 1]
    assert links[1].host_id == named.pk
    named.refresh_from_db()
    assert named.bio == "Updated"
    assert named.bio_html == "<p>Updated</p>"
    assert links[0].host.slug == "grace"
    assert links[0].host.bio_html == "<p>First</p>"
    identities = [link.pk for link in links]
    _sync_instructors(course, graph)
    repeated = list(CourseInstructor.objects.order_by("position").values_list("pk", flat=True))
    assert repeated == identities
    assert Host.objects.count() == 2
    reordered = (InstructorGraph("Renamed", slug="ada"), InstructorGraph("Grace"))
    _sync_instructors(course, SimpleNamespace(instructors=reordered))
    links = list(CourseInstructor.objects.order_by("position"))
    assert [link.host_id for link in links] == [named.pk, Host.objects.get(slug="grace").pk]
    named.refresh_from_db()
    assert named.bio == "Updated"


def main():
    assert not apps.is_installed("community_base.events")
    assert CourseInstructor._meta.get_field("host").remote_field.model is Host
    assert "kind" not in {field.name for field in Host._meta.concrete_fields}
    with connection.schema_editor() as editor:
        for model in (ContentSource, Host, Course, CourseInstructor):
            editor.create_model(model)
    course = Course.objects.create(slug="synthetic", title="Synthetic")
    if sys.argv[1] == "empty":
        _sync_instructors(course, SimpleNamespace(instructors=()))
        assert Host.objects.count() == 0
        assert CourseInstructor.objects.count() == 0
    else:
        check_instructor_import(course)
    assert "community_base.events.models" not in sys.modules
    print("site-events-import-passed")


if __name__ == "__main__":
    main()
