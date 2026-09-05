from urllib.parse import urlsplit


def safe_return_path(value, default="/"):
    if not isinstance(value, str):
        return default
    value = value.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return default
    if any(ord(character) < 32 for character in value):
        return default
    try:
        parsed = urlsplit(value)
    except ValueError:
        return default
    if parsed.scheme or parsed.netloc:
        return default
    return value
