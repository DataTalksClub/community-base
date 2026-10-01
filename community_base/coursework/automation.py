from dataclasses import dataclass

from community_base.config import is_enabled

COURSEWORK_AUTOMATION_KEY = "COURSEWORK_AUTOMATION_ENABLED"
GUARD_VERSION = "1"
GUARDED_HANDLERS = (
    "coursework.form_pooled_batches",
    "coursework.expire_pooled_reviews",
    "coursework.send_homework_deadline_reminders",
    "coursework.send_project_submission_deadline_reminders",
    "coursework.send_peer_review_deadline_reminders",
)
GUARDED_OPERATIONS = (
    "try_form_batch",
    "form_pooled_batches",
    "try_score_batch",
)


@dataclass(frozen=True, slots=True)
class CourseworkAutomationPolicy:
    enabled: bool
    guard_version: str = GUARD_VERSION
    guarded_handlers: tuple[str, ...] = GUARDED_HANDLERS
    guarded_operations: tuple[str, ...] = GUARDED_OPERATIONS


def get_automation_policy() -> CourseworkAutomationPolicy:
    return CourseworkAutomationPolicy(enabled=is_enabled(COURSEWORK_AUTOMATION_KEY))
