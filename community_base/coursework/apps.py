from django.apps import AppConfig

from community_base.kernel.conf import get


def studio_surface_enabled() -> bool:
    """Whether the package registers its coursework Studio section.

    The Studio views import `community_base.accounts.models.User`. A site that owns its own
    user app and Studio (AISL) installs coursework for its models and services only, and turns
    this off with `COMMUNITY_BASE["COURSEWORK_STUDIO_ENABLED"] = False`. A `COMMUNITY_BASE`
    setting rather than a runtime config key: it is read once in `ready()`, so a database
    override could never take effect.
    """

    return bool(get("COURSEWORK_STUDIO_ENABLED"))


def member_api_enabled() -> bool:
    """Whether importing `api_views` registers the member routes under the API registry.

    Off (`COMMUNITY_BASE["COURSEWORK_MEMBER_API_ENABLED"] = False`) for a site that keeps its
    own learner routes and must not expose the package leaderboard, certificate-request and
    preference endpoints.
    """

    return bool(get("COURSEWORK_MEMBER_API_ENABLED"))


class CourseworkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community_base.coursework"
    label = "cb_coursework"
    verbose_name = "Coursework"

    def ready(self):
        # C5.2g: pooling.py registers the coursework.expire_pooled_reviews job handler and its
        # schedule as module-level side effects; it must be imported eagerly here, the same way
        # reminders.py's three handlers already are, or a pooled site never registers it (every
        # other import of pooling.py is a lazy, function-local import to break an import cycle
        # with review.py/projects.py -- see those modules for why).
        from community_base.coursework import pooling, reminders  # noqa: F401

        if member_api_enabled():
            from community_base.coursework import api_views  # noqa: F401
        if studio_surface_enabled():
            from community_base.coursework.studio_registration import register_studio

            register_studio()
