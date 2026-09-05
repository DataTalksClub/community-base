from django.core.exceptions import ImproperlyConfigured


def submit(intent_id):
    try:
        from django_q.tasks import async_task  # type: ignore[import-untyped]
    except ImportError as error:
        raise ImproperlyConfigured(
            "The django_q jobs backend requires community-base[django_q]."
        ) from error
    return async_task(
        "community_base.jobs.runner.run_intent",
        str(intent_id),
        q_options={"task_name": f"community-base-job-{intent_id}", "ack_failure": True},
    )
