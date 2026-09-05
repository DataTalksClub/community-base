from django.db import IntegrityError, transaction
from django.utils import timezone

from community_base.jobs.models import JobIntent
from community_base.jobs.relay import RelayError, configured_client


def submit(intent_id) -> str:
    intent = JobIntent.objects.get(id=intent_id)
    if intent.external_id:
        return intent.external_id
    document = configured_client().submit_webhook(intent)
    task_id = document["id"]
    try:
        with transaction.atomic():
            updated = JobIntent.objects.filter(id=intent.id, external_id="").update(
                external_id=task_id,
                status=JobIntent.Status.SUBMITTED,
                updated_at=timezone.now(),
            )
    except IntegrityError as error:
        raise RelayError("relay_task_id_conflict") from error
    if updated == 0:
        intent.refresh_from_db(fields=("external_id",))
        if intent.external_id != task_id:
            raise RelayError("relay_submission_race")
    return task_id
