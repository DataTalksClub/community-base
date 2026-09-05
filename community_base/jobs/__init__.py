"""Durable background job API."""


def dispatch_after_commit(*args, **kwargs):
    from community_base.jobs.dispatch import dispatch_after_commit as dispatch

    return dispatch(*args, **kwargs)


def register_handler(*args, **kwargs):
    from community_base.jobs.registry import register_handler as register

    return register(*args, **kwargs)


def schedule(*args, **kwargs):
    from community_base.jobs.registry import schedule as register_schedule

    return register_schedule(*args, **kwargs)


def complete_chunked_job(*args, **kwargs):
    from community_base.jobs.chunked import complete_chunked_job as complete

    return complete(*args, **kwargs)


def fail_chunked_job(*args, **kwargs):
    from community_base.jobs.chunked import fail_chunked_job as fail

    return fail(*args, **kwargs)


__all__ = [
    "complete_chunked_job",
    "dispatch_after_commit",
    "fail_chunked_job",
    "register_handler",
    "schedule",
]
