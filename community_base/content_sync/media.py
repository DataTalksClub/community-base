from dataclasses import dataclass


@dataclass(frozen=True)
class MediaResult:
    path: str
    url: str


class NullMediaStore:
    """Default media boundary that leaves authored paths unchanged."""

    def upload(self, checkout, path, source):
        checkout.read_bytes(path)
        return MediaResult(str(path), str(path))


def media_store():
    return NullMediaStore()
