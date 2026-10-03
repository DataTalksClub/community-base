import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

CURRICULUM_APP = "cb_curriculum"
CURRICULUM_BEFORE = "0005_module_unit_source_sibling_position"
CURRICULUM_AFTER = "0006_courseenrollment"
COURSEWORK_APP = "cb_coursework"

pytestmark = pytest.mark.django_db(transaction=True)


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


def curriculum_targets(curriculum_target, current_targets):
    targets = [(CURRICULUM_APP, curriculum_target)]
    for node in current_targets:
        if node[0] == COURSEWORK_APP:
            targets.append(node)
    assert len(targets) > 1
    return targets


def project_link_column_shape():
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(
            cursor, "cb_coursework_projectsubmission"
        )
    for column in columns:
        if column.name == "github_link":
            # SQLite includes width in type_code; PostgreSQL exposes internal_size.
            return column.type_code, column.internal_size, column.null_ok
    pytest.fail("Project submission link column was not introspected")


def create_course_and_cohort(apps):
    course = apps.get_model(CURRICULUM_APP, "Course").objects.create(
        slug="migration-course",
        title="Migration Course",
        status="published",
        required_level=5,
    )
    cohort = apps.get_model(CURRICULUM_APP, "Cohort").objects.create(
        course=course,
        slug="2026",
        title="2026 cohort",
        start_date=datetime.date(2026, 1, 12),
        end_date=datetime.date(2026, 3, 30),
        max_participants=50,
    )
    return course, cohort


def create_existing_rows(apps):
    user = apps.get_model("accounts", "User").objects.create(
        email="migration@example.com",
        password="!",
    )
    course, cohort = create_course_and_cohort(apps)
    enrollment = apps.get_model(CURRICULUM_APP, "Enrollment").objects.create(
        user=user,
        cohort=cohort,
        source="admin",
        display_name="Migration Learner",
        total_score=37,
    )
    complaint = apps.get_model(COURSEWORK_APP, "LeaderboardComplaint").objects.create(
        enrollment=enrollment,
        reporter=user,
        issue_type="other",
        description="Synthetic migration fixture",
    )
    return {
        "course": course.pk,
        "cohort": cohort.pk,
        "enrollment": enrollment.pk,
        "complaint": complaint.pk,
    }


def snapshot_existing_rows(apps, row_ids):
    model_names = {
        "course": (CURRICULUM_APP, "Course"),
        "cohort": (CURRICULUM_APP, "Cohort"),
        "enrollment": (CURRICULUM_APP, "Enrollment"),
        "complaint": (COURSEWORK_APP, "LeaderboardComplaint"),
    }
    return {
        name: apps.get_model(*model_names[name]).objects.values().get(pk=pk)
        for name, pk in row_ids.items()
    }


def assert_snapshot_types(snapshot):
    assert isinstance(snapshot["course"]["id"], int)
    assert isinstance(snapshot["course"]["required_level"], int)
    assert isinstance(snapshot["cohort"]["start_date"], datetime.date)
    assert isinstance(snapshot["cohort"]["max_participants"], int)
    assert isinstance(snapshot["enrollment"]["enrolled_at"], datetime.datetime)
    assert isinstance(snapshot["enrollment"]["total_score"], int)
    assert isinstance(snapshot["complaint"]["created_at"], datetime.datetime)
    assert isinstance(snapshot["complaint"]["resolved"], bool)


def assert_forward_state(apps, row_ids, expected, previous_tables):
    course_enrollment = apps.get_model(CURRICULUM_APP, "CourseEnrollment")
    new_table = course_enrollment._meta.db_table
    assert set(connection.introspection.table_names()) - previous_tables == {new_table}
    assert course_enrollment.objects.count() == 0
    assert snapshot_existing_rows(apps, row_ids) == expected
    complaint = apps.get_model(COURSEWORK_APP, "LeaderboardComplaint").objects.get(
        pk=row_ids["complaint"]
    )
    assert complaint.enrollment_id == row_ids["enrollment"]
    return new_table


def assert_reversed_state(apps, row_ids, expected, previous_tables):
    assert set(connection.introspection.table_names()) == previous_tables
    with pytest.raises(LookupError):
        apps.get_model(CURRICULUM_APP, "CourseEnrollment")
    assert snapshot_existing_rows(apps, row_ids) == expected


def assert_reapplied_state(apps, row_ids, expected, previous_tables, new_table):
    course_enrollment = apps.get_model(CURRICULUM_APP, "CourseEnrollment")
    assert course_enrollment.objects.count() == 0
    assert set(connection.introspection.table_names()) - previous_tables == {new_table}
    assert snapshot_existing_rows(apps, row_ids) == expected


def test_course_enrollment_migration_preserves_cohort_and_coursework_rows():
    executor = MigrationExecutor(connection)
    current_targets = executor.loader.graph.leaf_nodes()
    applied_before = set(MigrationRecorder(connection).applied_migrations())
    assert set(current_targets) <= applied_before
    column_before = project_link_column_shape()
    previous_targets = curriculum_targets(CURRICULUM_BEFORE, current_targets)
    new_targets = curriculum_targets(CURRICULUM_AFTER, current_targets)
    try:
        check_migration_round_trip(previous_targets, new_targets)
    finally:
        migrate(current_targets)
    assert set(MigrationRecorder(connection).applied_migrations()) == applied_before
    assert project_link_column_shape() == column_before


def check_migration_round_trip(previous_targets, new_targets):
    previous_apps = migrate(previous_targets)
    previous_tables = set(connection.introspection.table_names())
    row_ids = create_existing_rows(previous_apps)
    expected = snapshot_existing_rows(previous_apps, row_ids)
    assert_snapshot_types(expected)

    new_table = assert_forward_state(migrate(new_targets), row_ids, expected, previous_tables)

    assert_reversed_state(migrate(previous_targets), row_ids, expected, previous_tables)

    assert_reapplied_state(migrate(new_targets), row_ids, expected, previous_tables, new_table)
