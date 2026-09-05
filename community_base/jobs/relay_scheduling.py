from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured

from community_base.jobs.registry import registered_schedules
from community_base.jobs.relay import RelayClient, RelaySchedule
from community_base.kernel.conf import get


@dataclass(frozen=True, slots=True)
class RelayScheduleSpec:
    name: str
    cron: str
    payload: dict


def desired_relay_schedules() -> tuple[RelayScheduleSpec, ...]:
    site_key = get("SITE_KEY")
    if not isinstance(site_key, str) or not site_key:
        raise ImproperlyConfigured("SITE_KEY must be configured for Relay schedules")
    site_url = get("SITE_URL")
    if not isinstance(site_url, str) or not site_url:
        raise ImproperlyConfigured("SITE_URL must be configured for Relay schedules")
    result = []
    for definition in registered_schedules():
        remote_name = f"community-base:{site_key}:{definition.name}"
        if len(remote_name) > 120:
            raise ImproperlyConfigured("Relay schedule name exceeds 120 characters")
        result.append(
            RelayScheduleSpec(
                name=remote_name,
                cron=definition.cron,
                payload={
                    "name": remote_name,
                    "cron": definition.cron,
                    "type": "webhook",
                    "url": f"{site_url.rstrip('/')}/internal/jobs/run",
                    "params": {"schedule_name": definition.name},
                    "enabled": True,
                },
            )
        )
    return tuple(result)


def relay_schedule_changes(
    existing: tuple[RelaySchedule, ...],
) -> tuple[tuple[str, str, str | None], ...]:
    prefix = f"community-base:{get('SITE_KEY')}:"
    managed = {item.name: item for item in existing if item.name.startswith(prefix)}
    changes = []
    desired_names = set()
    for spec in desired_relay_schedules():
        desired_names.add(spec.name)
        current = managed.get(spec.name)
        if current is None:
            action = "create"
        elif _matches(current, spec):
            action = "unchanged"
        else:
            action = "update"
        changes.append((action, spec.name, current.id if current else None))
    changes.extend(
        ("delete", name, managed[name].id)
        for name in sorted(managed.keys() - desired_names)
        if managed[name].enabled
    )
    return tuple(changes)


def sync_relay_schedules(client: RelayClient, *, dry_run: bool = False):
    existing = client.schedules()
    changes = relay_schedule_changes(existing)
    if dry_run:
        return changes
    specs = {item.name: item for item in desired_relay_schedules()}
    for action, name, schedule_id in changes:
        if action in {"create", "update"}:
            client.upsert_schedule(specs[name].payload)
        elif action == "delete" and schedule_id is not None:
            client.delete_schedule(schedule_id)
    return changes


def _matches(current: RelaySchedule, desired: RelayScheduleSpec) -> bool:
    return (
        current.cron == desired.cron
        and current.task_type == "webhook"
        and current.enabled
        and current.task.get("url") == desired.payload["url"]
        and current.task.get("payload") == desired.payload["params"]
    )
