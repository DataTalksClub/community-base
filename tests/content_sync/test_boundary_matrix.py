import hashlib
import hmac
import io
import json
import tarfile
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.urls import reverse

from community_base.content_sync.checkout import CheckoutError, ImmutableCheckout
from community_base.content_sync.github import GitHubClient, GitHubClientError, checkout_repository
from community_base.content_sync.media import S3MediaStore
from community_base.content_sync.models import ContentSource, WebhookLog

SHA = "a" * 40


class NoRequestSession:
    def request(self, *args, **kwargs):
        raise AssertionError("invalid input must be rejected before an HTTP request")


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "..",
        "../one.md",
        "content/../one.md",
        "/one.md",
        "//server/one.md",
        "content/.",
        "content//missing.md",
        "missing.md",
        "content\\one.md",
        "content/one.md/child",
    ],
)
def test_checkout_rejects_paths_outside_its_manifest(tmp_path, path):
    (tmp_path / "one.md").write_text("one")
    with ImmutableCheckout(tmp_path) as checkout:
        with pytest.raises(CheckoutError):
            checkout.read_bytes(path)


@override_settings(COMMUNITY_BASE={})
@pytest.mark.parametrize(
    "repo_name",
    [
        "",
        "owner",
        "/repo",
        "owner/",
        "owner/repo/extra",
        "owner name/repo",
        "owner/repo name",
        "owner:repo",
        "https://github.com/owner/repo",
        "owner@host/repo",
        "owner/repo?ref=main",
        "../repo",
        "owner/..",
        "./repo",
    ],
)
def test_github_repository_identifier_validation_precedes_network(repo_name):
    client = GitHubClient(session=NoRequestSession())
    with pytest.raises(GitHubClientError, match="repository name"):
        client.resolve_commit(repo_name)


@override_settings(COMMUNITY_BASE={})
@pytest.mark.parametrize(
    "commit_sha",
    [
        "",
        "a" * 39,
        "a" * 41,
        "A" * 40,
        "g" * 40,
        "main",
        "HEAD",
        "a" * 39 + "/",
        "../" + "a" * 37,
        "a" * 20 + " " + "a" * 19,
        "0x" + "a" * 38,
        "a" * 40 + "?x",
    ],
)
def test_github_archive_requires_canonical_commit_sha(tmp_path, commit_sha):
    client = GitHubClient(session=NoRequestSession())
    with pytest.raises(GitHubClientError, match="commit SHA"):
        client.download_archive("owner/repo", commit_sha, tmp_path / "archive", private=False)


def _signed_headers(body):
    digest = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_HUB_SIGNATURE_256": f"sha256={digest}",
        "HTTP_X_GITHUB_DELIVERY": "delivery",
        "HTTP_X_GITHUB_EVENT": "push",
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body,header_change,expected",
    [
        (b"not-json", {}, 400),
        (b"[]", {}, 400),
        (b"{}", {}, 400),
        (b'{"repository": {}}', {}, 400),
        (b'{"repository": {"full_name": null}}', {}, 400),
        (None, {"HTTP_X_GITHUB_DELIVERY": ""}, 400),
        (None, {"HTTP_X_GITHUB_DELIVERY": "x" * 201}, 400),
        (None, {"HTTP_X_GITHUB_EVENT": ""}, 400),
        (None, {"HTTP_X_HUB_SIGNATURE_256": ""}, 401),
        (None, {"HTTP_X_HUB_SIGNATURE_256": "sha1=" + "0" * 40}, 401),
        (None, {"HTTP_X_HUB_SIGNATURE_256": "sha256=" + "A" * 64}, 401),
        (None, {"HTTP_X_HUB_SIGNATURE_256": "sha256=abc"}, 401),
        (None, {"HTTP_X_HUB_SIGNATURE_256": "sha256=" + "0" * 65}, 401),
        (None, {"HTTP_X_HUB_SIGNATURE_256": "sha256=" + "0" * 64 + "x"}, 401),
        (None, {"HTTP_X_HUB_SIGNATURE_256": "sha256=" + "0" * 64}, 401),
    ],
)
def test_webhook_rejects_malformed_or_unsigned_inputs(client, body, header_change, expected):
    ContentSource.objects.create(
        slug="source", repo_name="owner/repo", webhook_secret="webhook-secret"
    )
    if body is None:
        body = json.dumps(
            {"repository": {"full_name": "owner/repo", "default_branch": "main"}}
        ).encode()
    headers = _signed_headers(body)
    headers.update(header_change)

    response = client.post(
        reverse("cb_content_sync:github_webhook"),
        data=body,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == expected
    assert not WebhookLog.objects.exists()


class ArchiveResponse:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return {"sha": SHA}

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.body


class ArchiveSession:
    def __init__(self, body):
        self.body = body
        self.calls = 0

    def request(self, *args, **kwargs):
        self.calls += 1
        return ArchiveResponse(b"" if self.calls == 1 else self.body)


def _special_archive(member_type, name="unsafe"):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        root = tarfile.TarInfo("root")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo(f"root/{name}")
        member.type = member_type
        if member_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
            member.linkname = "target"
        archive.addfile(member)
    return payload.getvalue()


@override_settings(COMMUNITY_BASE={})
@pytest.mark.parametrize(
    "member_type",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
    ],
)
def test_github_archive_rejects_every_link_and_special_file_type(member_type):
    session = ArchiveSession(_special_archive(member_type))
    source = SimpleNamespace(repo_name="owner/repo", is_private=False, max_files=10)
    with pytest.raises(CheckoutError, match="link or special"):
        with checkout_repository(source, client=GitHubClient(session=session)):
            pass


class MediaCheckout:
    def __init__(self, path):
        self.path = path

    def read_bytes(self, path):
        assert path == self.path
        return b"payload"


class MediaClient:
    def __init__(self):
        self.call = None

    def put_object(self, **kwargs):
        self.call = kwargs


@override_settings(COMMUNITY_BASE={"CONTENT_SYNC_S3_BUCKET": "bucket"})
@pytest.mark.parametrize(
    "path,content_type",
    [
        ("image.jpg", "image/jpeg"),
        ("image.jpeg", "image/jpeg"),
        ("image.png", "image/png"),
        ("image.gif", "image/gif"),
        ("image.webp", "image/webp"),
        ("document.pdf", "application/pdf"),
        ("data.json", "application/json"),
        ("unknown.bin", "application/octet-stream"),
    ],
)
def test_s3_media_content_type_matrix(path, content_type):
    client = MediaClient()
    store = S3MediaStore(client=client)
    store.upload(MediaCheckout(path), path, SimpleNamespace(slug="source"))
    assert client.call["ContentType"] == content_type
