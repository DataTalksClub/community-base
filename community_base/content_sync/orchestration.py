from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from community_base.content_sync.checkout import ImmutableCheckout, git_commit_sha
from community_base.content_sync.media import media_store
from community_base.content_sync.models import ContentSource, SyncLog, SyncStatus
from community_base.content_sync.parsers import parsers
from community_base.kernel import conf
from community_base.kernel.redaction import mask_sensitive_spans

LOCK_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class UpsertResult:
    obj: object
    action: str = "unchanged"

    def __post_init__(self):
        if self.action not in {"created", "updated", "unchanged"}:
            raise ValueError("Unknown content sync action")


def acquire_source_lock(source):
    now = timezone.now()
    with transaction.atomic():
        locked = ContentSource.objects.select_for_update().get(pk=source.pk)
        if locked.sync_locked_at:
            age = (now - locked.sync_locked_at).total_seconds()
            if age < LOCK_TIMEOUT_SECONDS:
                locked.sync_requested = True
                locked.save(update_fields=("sync_requested", "updated_at"))
                return False
        locked.sync_locked_at = now
        locked.sync_requested = False
        locked.save(update_fields=("sync_locked_at", "sync_requested", "updated_at"))
    source.refresh_from_db()
    return True


def release_source_lock(source, *, follow_up_key=None):
    with transaction.atomic():
        locked = ContentSource.objects.select_for_update().get(pk=source.pk)
        follow_up = locked.sync_requested
        locked.sync_locked_at = None
        locked.sync_requested = False
        locked.save(update_fields=("sync_locked_at", "sync_requested", "updated_at"))
        if follow_up and follow_up_key:
            from community_base.content_sync.queue import queue_source_sync

            queue_source_sync(locked, key=f"follow-up:{follow_up_key}")


def _outcome(value):
    if isinstance(value, UpsertResult):
        return value
    action = getattr(value, "_content_sync_action", "unchanged")
    return UpsertResult(value, action)


def _deleted_count(value):
    if isinstance(value, int):
        return value
    return len(list(value or ()))


def _safe_error(source, error):
    return mask_sensitive_spans(
        str(error),
        canaries=(
            source.webhook_secret,
            str(conf.get("CONTENT_SYNC_GITHUB_PRIVATE_KEY")),
        ),
    )[:1000]


def sync_content_source(source, *, repo_dir=None, batch_id=None, force=False):
    source = ContentSource.objects.get(pk=source.pk)
    if not source.is_enabled and not force:
        return SyncLog.objects.create(
            source=source, batch_id=batch_id, status=SyncStatus.SKIPPED, finished_at=timezone.now()
        )
    if not acquire_source_lock(source):
        return SyncLog.objects.create(
            source=source,
            batch_id=batch_id,
            status=SyncStatus.SKIPPED,
            finished_at=timezone.now(),
            warnings=["Sync already running; follow-up requested"],
        )

    log = SyncLog.objects.create(source=source, batch_id=batch_id, status=SyncStatus.RUNNING)
    try:
        if repo_dir is None:
            from community_base.content_sync.github import GitHubClient, checkout_repository

            client = GitHubClient()
            commit_sha = client.resolve_commit(source.repo_name, private=source.is_private)
            if (
                not force
                and source.last_synced_commit == commit_sha
                and source.last_sync_status in {SyncStatus.SUCCESS, SyncStatus.SKIPPED}
            ):
                log.commit_sha = commit_sha
                log.status = SyncStatus.SKIPPED
                log.warnings = ["Repository commit was already synchronized"]
                log.finished_at = timezone.now()
                log.save(update_fields=("commit_sha", "status", "warnings", "finished_at"))
                ContentSource.objects.filter(pk=source.pk).update(
                    last_sync_status=SyncStatus.SKIPPED,
                    last_synced_at=log.finished_at,
                )
                return log
            checkout_context = checkout_repository(source, client=client, commit_sha=commit_sha)
        else:
            path = Path(repo_dir)
            checkout_context = ImmutableCheckout(
                path, commit_sha=git_commit_sha(path), max_files=source.max_files
            )
        with checkout_context as checkout:
            log.commit_sha = checkout.commit_sha
            details = []
            errors = []
            counts = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0}
            media = media_store()
            for content_type, parser in parsers():
                seen = set()
                try:
                    items = list(parser.discover(checkout, source))
                    for item in items:
                        if item.key in seen:
                            raise ValueError(f"Duplicate source key: {item.key}")
                        seen.add(item.key)
                        result = _outcome(parser.upsert(item, source, media))
                        counts[result.action] += 1
                        if result.action != "unchanged":
                            details.append(
                                {
                                    "key": item.key,
                                    "path": str(item.path),
                                    "action": result.action,
                                    "content_type": content_type,
                                }
                            )
                    deleted = _deleted_count(parser.soft_delete_missing(seen, source))
                    counts["deleted"] += deleted
                except Exception as error:
                    errors.append(
                        {"content_type": content_type, "error": _safe_error(source, error)}
                    )

            log.items_created = counts["created"]
            log.items_updated = counts["updated"]
            log.items_unchanged = counts["unchanged"]
            log.items_deleted = counts["deleted"]
            log.items_detail = details
            log.errors = errors
            log.status = SyncStatus.PARTIAL if errors else SyncStatus.SUCCESS
            log.finished_at = timezone.now()
            log.save()
            source.last_synced_at = log.finished_at
            source.last_sync_status = log.status
            source.last_sync_log = "; ".join(error["error"] for error in errors)
            if not errors and log.commit_sha:
                source.last_synced_commit = log.commit_sha
            source.save(
                update_fields=(
                    "last_synced_at",
                    "last_sync_status",
                    "last_sync_log",
                    "last_synced_commit",
                    "updated_at",
                )
            )
            return log
    except Exception as error:
        safe_error = _safe_error(source, error)
        log.status = SyncStatus.FAILED
        log.errors = [{"error": safe_error}]
        log.finished_at = timezone.now()
        log.save(update_fields=("status", "errors", "finished_at"))
        ContentSource.objects.filter(pk=source.pk).update(
            last_synced_at=log.finished_at,
            last_sync_status=SyncStatus.FAILED,
            last_sync_log=safe_error,
        )
        return log
    finally:
        release_source_lock(source, follow_up_key=log.pk)
