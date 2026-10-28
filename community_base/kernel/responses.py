def no_store(response):
    """Mark a member-specific response as private and never cached."""

    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    return response
