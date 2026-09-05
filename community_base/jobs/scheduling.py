from __future__ import annotations

import ast
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from community_base.jobs.dispatch import dispatch_after_commit
from community_base.jobs.registry import registered_schedules

RUN_DUE_NAME = "community-base:jobs-run-due"


@dataclass(frozen=True, slots=True)
class LocalScheduleSpec:
    name: str
    func: str
    cron: str
    kwargs: dict


def desired_local_schedules() -> tuple[LocalScheduleSpec, ...]:
    desired = [
        LocalScheduleSpec(
            name=RUN_DUE_NAME,
            func="community_base.jobs.operations.run_due",
            cron="* * * * *",
            kwargs={"q_options": {"task_name": RUN_DUE_NAME}},
        )
    ]
    for definition in registered_schedules():
        name = f"community-base:{definition.name}"
        desired.append(
            LocalScheduleSpec(
                name=name,
                func="community_base.jobs.scheduling.dispatch_registered_schedule",
                cron=definition.cron,
                kwargs={
                    "schedule_name": definition.name,
                    "q_options": {"task_name": name},
                },
            )
        )
    return tuple(desired)


def schedule_changes(existing: dict[str, dict]) -> tuple[tuple[str, str], ...]:
    changes = []
    for spec in desired_local_schedules():
        current = existing.get(spec.name)
        expected = {"func": spec.func, "cron": spec.cron, "kwargs": spec.kwargs, "repeats": -1}
        action = "create" if current is None else "unchanged" if current == expected else "update"
        changes.append((action, spec.name))
    return tuple(changes)


def parse_stored_kwargs(value) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def dispatch_registered_schedule(*, schedule_name: str) -> str:
    definitions = {item.name: item for item in registered_schedules()}
    definition = definitions.get(schedule_name)
    if definition is None:
        raise ValueError("unknown registered job schedule")
    minute = timezone.now().replace(second=0, microsecond=0).isoformat()
    with transaction.atomic():
        intent, _ = dispatch_after_commit(
            definition.handler,
            key=f"schedule:{schedule_name}:{minute}",
            payload=definition.payload,
        )
    return str(intent.id)
