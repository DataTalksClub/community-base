from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from community_base.content_sync.media import (
    MediaStoreError,
    NullMediaStore,
    S3MediaStore,
    media_store,
)


class Checkout:
    def read_bytes(self, path):
        assert str(path) == "images/a picture.png"
        return b"image-bytes"


class Escaping:
    def read_bytes(self, path):
        return b"image-bytes"


class Client:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


@override_settings(COMMUNITY_BASE={})
def test_null_store_is_the_safe_default():
    assert isinstance(media_store(), NullMediaStore)


@override_settings(COMMUNITY_BASE={})
def test_null_store_returns_a_site_absolute_url():
    # The sanitiser drops an img src that is neither site-absolute nor an
    # absolute http(s) URL, so a repository path returned as the URL would be
    # silently discarded at render time (D37).
    result = NullMediaStore().upload(Checkout(), "images/a picture.png", SimpleNamespace())

    assert result.path == "images/a picture.png"
    assert result.url == "/media/content-sync/images/a%20picture.png"


@override_settings(COMMUNITY_BASE={"CONTENT_SYNC_NULL_MEDIA_URL_PREFIX": "/assets/"})
def test_null_store_url_prefix_is_configurable():
    result = NullMediaStore().upload(Checkout(), "images/a picture.png", SimpleNamespace())

    assert result.url == "/assets/images/a%20picture.png"


@override_settings(COMMUNITY_BASE={"CONTENT_SYNC_NULL_MEDIA_URL_PREFIX": ""})
def test_null_store_url_stays_site_absolute_without_a_prefix():
    result = NullMediaStore().upload(Checkout(), "images/a picture.png", SimpleNamespace())

    assert result.url == "/images/a%20picture.png"


@pytest.mark.parametrize("path", ["../secrets/key.png", "/etc/passwd"])
@override_settings(COMMUNITY_BASE={})
def test_null_store_refuses_a_path_that_escapes_the_checkout(path):
    with pytest.raises(MediaStoreError):
        NullMediaStore().upload(Escaping(), path, SimpleNamespace())


@override_settings(
    COMMUNITY_BASE={
        "CONTENT_SYNC_MEDIA_BACKEND": "s3",
        "CONTENT_SYNC_S3_BUCKET": "media-bucket",
        "CONTENT_SYNC_S3_PREFIX": "content",
        "CONTENT_SYNC_S3_PUBLIC_URL": "https://media.example.com",
    }
)
def test_s3_store_uses_content_addressed_key_and_public_url():
    client = Client()
    store = S3MediaStore(client=client)

    result = store.upload(Checkout(), "images/a picture.png", SimpleNamespace(slug="source"))

    call = client.calls[0]
    assert call["Bucket"] == "media-bucket"
    assert call["Body"] == b"image-bytes"
    assert call["ContentType"] == "image/png"
    assert call["Key"].startswith("content/source/")
    assert call["Key"].endswith("/images/a picture.png")
    assert call["Metadata"]["sha256"] in call["Key"]
    assert result.url.startswith("https://media.example.com/content/source/")
    assert result.url.endswith("/images/a%20picture.png")


@override_settings(
    COMMUNITY_BASE={
        "CONTENT_SYNC_MEDIA_BACKEND": "s3",
        "CONTENT_SYNC_S3_BUCKET": "media-bucket",
    }
)
def test_s3_error_is_redacted():
    store = S3MediaStore(client=Client(RuntimeError("credential-canary")))

    with pytest.raises(MediaStoreError) as captured:
        store.upload(Checkout(), "images/a picture.png", SimpleNamespace(slug="source"))

    assert str(captured.value) == "S3 media upload failed"


@override_settings(COMMUNITY_BASE={"CONTENT_SYNC_MEDIA_BACKEND": "s3"})
def test_s3_backend_requires_bucket():
    with pytest.raises(ImproperlyConfigured, match="S3_BUCKET"):
        S3MediaStore(client=Client())


@override_settings(COMMUNITY_BASE={"CONTENT_SYNC_MEDIA_BACKEND": "unknown"})
def test_unknown_media_backend_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="Unsupported"):
        media_store()
