"""Access checks for curriculum content.

Level resolution follows the donor chain: a unit's own override wins, then
the course default, then the course ``required_level``. The level itself is
checked through the configured kernel access policy; individual purchase
access is delegated to the site through ``COURSE_ACCESS_GRANTS`` (AISL
implements it with its ``CourseAccess`` rows).
"""

from community_base.curriculum.models import Course, Unit
from community_base.kernel import access as kernel_access
from community_base.kernel.conf import get
from community_base.kernel.hooks import resolve

COURSE_LEVEL_CHOICES = (
    (kernel_access.LEVEL_OPEN, "Open (everyone)"),
    (kernel_access.LEVEL_BASIC, "Basic and above"),
    (kernel_access.LEVEL_MAIN, "Main and above"),
    (kernel_access.LEVEL_PREMIUM, "Premium only"),
)
UNIT_LEVEL_CHOICES = (
    (kernel_access.LEVEL_OPEN, "Open (everyone)"),
    (kernel_access.LEVEL_REGISTERED, "Registered users"),
    (kernel_access.LEVEL_BASIC, "Basic and above"),
    (kernel_access.LEVEL_MAIN, "Main and above"),
    (kernel_access.LEVEL_PREMIUM, "Premium only"),
)


def purchase_grants(user, course: Course) -> bool:
    """Return True when the site's purchase hook grants this user the course."""

    target = get("COURSE_ACCESS_GRANTS")
    if target is None:
        return False
    grants = resolve(target) if isinstance(target, str) else target
    return bool(grants(user, course))


def _course_for(obj):
    if isinstance(obj, Course):
        return obj
    if isinstance(obj, Unit):
        return obj.module.cohort.course
    raise TypeError(f"Unsupported curriculum access object: {type(obj).__name__}")


def can_access(user, obj) -> bool:
    """Return whether ``user`` may read the course or unit ``obj``.

    ``Unit.is_preview`` is intentionally not collapsed into this check:
    callers test it first because the flag also drives template branches
    such as the sidebar preview badge.
    """

    level = getattr(obj, "effective_required_level", None)
    if level is None:
        level = obj.required_level
    if kernel_access.can_access(user, level):
        return True
    if user is not None and user.is_authenticated:
        return purchase_grants(user, _course_for(obj))
    return False


def gated_reason(user, obj) -> str:
    """Return why access is denied, or an empty string when access is allowed."""

    if can_access(user, obj):
        return ""
    if user is None or not user.is_authenticated:
        return "authentication_required"
    return "insufficient_level"
