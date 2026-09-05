import csv
import io
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from community_base.accounts.models import (
    IMPORT_BATCH_SOURCE_CHOICES,
    ImportBatch,
)
from community_base.accounts.services.email_resolution import normalize_email, resolve_user_by_email
from community_base.accounts.services.free_welcome import send_free_welcome


@dataclass(frozen=True, slots=True)
class ImportRow:
    email: str
    first_name: str = ""
    last_name: str = ""
    email_verified: bool = False
    account_activated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportResult:
    batch: ImportBatch | None
    dry_run: bool
    users_created: int
    users_updated: int
    users_skipped: int
    emails_queued: int
    errors: tuple[dict[str, Any], ...]


_ADAPTERS = {}
SAFE_EXTRA_FIELDS = {
    "slack_user_id",
    "slack_member",
    "preferred_timezone",
    "theme_preference",
    "tags",
}


def register_import_adapter(source, adapter):
    if source not in dict(IMPORT_BATCH_SOURCE_CHOICES):
        raise ValueError(f"Unsupported import source: {source}")
    if not callable(adapter):
        raise TypeError("Import adapter must be callable")
    _ADAPTERS[source] = adapter


def get_import_adapter(source):
    try:
        return _ADAPTERS[source]
    except KeyError as error:
        raise ValueError(f"No import adapter registered for {source}") from error


def rows_from_csv(content):
    if hasattr(content, "read"):
        content = content.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    if not isinstance(content, str):
        raise TypeError("CSV content must be text, bytes, or a readable file")
    content = content.removeprefix("\ufeff")
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or "email" not in {name.strip().lower() for name in reader.fieldnames}:
        raise ValueError("CSV must contain an email column")
    for raw in reader:
        normalized = {str(key).strip().lower(): (value or "").strip() for key, value in raw.items()}
        name = normalized.get("name", "")
        parts = name.split(maxsplit=1)
        yield ImportRow(
            email=normalized.get("email", ""),
            first_name=normalized.get("first_name", "") or (parts[0] if parts else ""),
            last_name=normalized.get("last_name", "") or (parts[1] if len(parts) == 2 else ""),
            email_verified=normalized.get("email_verified", "").lower() in {"1", "true", "yes"},
            metadata={
                key: value
                for key, value in normalized.items()
                if key not in {"email", "name", "first_name", "last_name", "email_verified"}
                and value
            },
        )


def _coerce_row(row):
    if isinstance(row, ImportRow):
        return row
    if isinstance(row, dict):
        return ImportRow(**row)
    raise TypeError("Import rows must be ImportRow objects or dictionaries")


def _apply_row(source, row, *, send_welcome):
    email = normalize_email(row.email)
    if not email or "@" not in email:
        raise ValueError("A valid email is required")
    unknown = set(row.fields) - SAFE_EXTRA_FIELDS
    if unknown:
        raise ValueError(f"Unsupported imported field(s): {', '.join(sorted(unknown))}")
    user = resolve_user_by_email(email)
    created = user is None
    if created:
        user = get_user_model().objects.create_user(
            email=email,
            signup_source="imported",
            import_source=source,
            imported_at=timezone.now(),
        )
    changed = []
    for name, value in (
        ("first_name", row.first_name.strip()),
        ("last_name", row.last_name.strip()),
    ):
        if value and not getattr(user, name):
            setattr(user, name, value[:150])
            changed.append(name)
    for name, value in row.fields.items():
        if getattr(user, name) != value:
            setattr(user, name, value)
            changed.append(name)
    if row.email_verified and not user.email_verified:
        user.email_verified = True
        changed.append("email_verified")
    if row.account_activated and not user.account_activated:
        user.account_activated = True
        changed.append("account_activated")
    metadata = {**(user.import_metadata or {}), **row.metadata}
    if metadata != user.import_metadata:
        user.import_metadata = metadata
        changed.append("import_metadata")
    if not created:
        if user.import_source != source:
            user.import_source = source
            changed.append("import_source")
        user.imported_at = timezone.now()
        changed.append("imported_at")
    if changed:
        user.save(update_fields=sorted(set(changed)))
    delivery = send_free_welcome(user) if created and send_welcome else None
    return created, bool(changed), delivery is not None


def run_import_batch(source, rows, *, actor=None, dry_run=False, send_welcome=False, params=None):
    if source not in dict(IMPORT_BATCH_SOURCE_CHOICES):
        raise ValueError(f"Unsupported import source: {source}")
    counts = {"created": 0, "updated": 0, "skipped": 0, "emails": 0}
    errors = []
    batch = None
    with transaction.atomic():
        batch = ImportBatch.objects.create(
            source=source,
            actor=actor,
            dry_run=dry_run,
            params=params or {},
        )
        for number, raw_row in enumerate(rows, start=2):
            try:
                created, updated, emailed = _apply_row(
                    source,
                    _coerce_row(raw_row),
                    send_welcome=send_welcome,
                )
            except (TypeError, ValueError) as error:
                counts["skipped"] += 1
                errors.append({"row": number, "error": str(error)})
                continue
            counts["created" if created else "updated" if updated else "skipped"] += 1
            counts["emails"] += int(emailed)
        batch.status = ImportBatch.Status.COMPLETED
        batch.finished_at = timezone.now()
        batch.users_created = counts["created"]
        batch.users_updated = counts["updated"]
        batch.users_skipped = counts["skipped"]
        batch.emails_queued = counts["emails"]
        batch.errors = errors
        batch.summary = (
            f"created={counts['created']} updated={counts['updated']} "
            f"skipped={counts['skipped']} emails={counts['emails']}"
        )
        batch.save(
            update_fields=(
                "status",
                "finished_at",
                "users_created",
                "users_updated",
                "users_skipped",
                "emails_queued",
                "errors",
                "summary",
            )
        )
        result = ImportResult(
            None if dry_run else batch,
            dry_run,
            counts["created"],
            counts["updated"],
            counts["skipped"],
            counts["emails"],
            tuple(errors),
        )
        if dry_run:
            transaction.set_rollback(True)
    return result


def run_registered_import(source, payload, **kwargs):
    return run_import_batch(source, get_import_adapter(source)(payload), **kwargs)
