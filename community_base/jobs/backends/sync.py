def submit(intent_id) -> str:
    from community_base.jobs.runner import run_intent

    return run_intent(intent_id, worker_id="sync")
