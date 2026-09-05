def allow_all(**kwargs) -> bool:
    """Default mail preference resolver."""

    del kwargs
    return True
