from community_base.jobs.registry import JobContext, JobPayload, register_handler


@register_handler("system.noop")
def noop(context: JobContext, payload: JobPayload) -> None:
    del context, payload
