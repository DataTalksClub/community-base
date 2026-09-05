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


__all__ = ["dispatch_after_commit", "register_handler", "schedule"]
