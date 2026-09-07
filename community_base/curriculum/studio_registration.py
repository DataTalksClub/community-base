from community_base.studio.registry import Destination, Section, register

CURRICULUM_STUDIO_ROUTES = (
    "curriculum_studio_course_list",
    "curriculum_studio_course_create",
    "curriculum_studio_course_detail",
    "curriculum_studio_course_edit",
    "curriculum_studio_course_delete",
    "curriculum_studio_instructor_add",
    "curriculum_studio_instructor_remove",
    "curriculum_studio_cohort_create",
    "curriculum_studio_cohort_detail",
    "curriculum_studio_cohort_edit",
    "curriculum_studio_cohort_delete",
    "curriculum_studio_module_create",
    "curriculum_studio_module_edit",
    "curriculum_studio_module_delete",
    "curriculum_studio_unit_create",
    "curriculum_studio_unit_edit",
    "curriculum_studio_unit_delete",
    "curriculum_studio_enrollment_create",
    "curriculum_studio_enrollment_delete",
    "curriculum_studio_certificate_issue",
)


def register_studio():
    register(
        Section(
            slug="courses",
            title="Courses",
            order=35,
            icon="book",
            destinations=(
                Destination(
                    key="courses",
                    title="Courses",
                    url_name="curriculum_studio_course_list",
                    route_names=CURRICULUM_STUDIO_ROUTES,
                    order=10,
                ),
            ),
        )
    )
