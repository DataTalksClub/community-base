from community_base.kernel.access import can_access
from community_base.onboarding.models import FlowAssignment, OnboardingFlow


def flow_for(user):
    """Return the highest-priority matching active flow, then the active default."""
    group_ids = set()
    if getattr(user, "is_authenticated", False):
        group_ids = set(user.groups.values_list("pk", flat=True))

    assignments = FlowAssignment.objects.select_related("flow").filter(flow__active=True)
    for assignment in assignments:
        group_match = assignment.group_id is not None and assignment.group_id in group_ids
        level_match = assignment.min_level is not None and can_access(user, assignment.min_level)
        if group_match or level_match:
            return assignment.flow

    return OnboardingFlow.objects.filter(active=True, is_default=True).first()
