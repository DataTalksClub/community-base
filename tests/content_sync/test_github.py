import io
import tarfile
from types import SimpleNamespace

import pytest
import requests
from django.test import override_settings

from community_base.content_sync.checkout import CheckoutError
from community_base.content_sync.github import GitHubClient, GitHubClientError, checkout_repository

SHA = "a" * 40


class Response:
    def __init__(self, *, status=200, json_data=None, body=b""):
        self.status_code = status
        self._json_data = json_data
        self.body = body

    def json(self):
        return self._json_data

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def archive_bytes(entries):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        root = tarfile.TarInfo("owner-repo-sha")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, body, kind in entries:
            info = tarfile.TarInfo(f"owner-repo-sha/{name}")
            if kind == "file":
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            elif kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = "elsewhere"
                archive.addfile(info)
    return payload.getvalue()


@override_settings(COMMUNITY_BASE={})
def test_checkout_resolves_head_then_reads_pinned_archive():
    body = archive_bytes([("content/item.md", b"hello", "file")])
    session = Session([Response(json_data={"sha": SHA}), Response(body=body)])
    source = SimpleNamespace(repo_name="owner/repo", is_private=False, max_files=10)

    with checkout_repository(source, client=GitHubClient(session=session)) as checkout:
        assert checkout.commit_sha == SHA
        assert checkout.read_text("content/item.md") == "hello"

    assert session.calls[0][1].endswith("/repos/owner/repo/commits/HEAD")
    assert session.calls[1][1].endswith(f"/repos/owner/repo/tarball/{SHA}")


@override_settings(COMMUNITY_BASE={})
def test_public_checkout_rejects_archive_links():
    body = archive_bytes([("content/link", b"", "link")])
    session = Session([Response(json_data={"sha": SHA}), Response(body=body)])
    source = SimpleNamespace(repo_name="owner/repo", is_private=False, max_files=10)

    with pytest.raises(CheckoutError, match="link or special"):
        with checkout_repository(source, client=GitHubClient(session=session)):
            pass


@override_settings(COMMUNITY_BASE={"CONTENT_SYNC_MAX_ARCHIVE_BYTES": 3})
def test_archive_size_is_bounded(tmp_path):
    client = GitHubClient(session=Session([Response(body=b"four")]))

    with pytest.raises(CheckoutError, match="size limit"):
        client.download_archive("owner/repo", SHA, tmp_path / "archive", private=False)


@override_settings(COMMUNITY_BASE={})
def test_private_source_requires_complete_app_credentials():
    client = GitHubClient(session=Session([]))

    with pytest.raises(GitHubClientError, match="credentials are required"):
        client.resolve_commit("owner/repo", private=True)


@override_settings(COMMUNITY_BASE={})
def test_transport_error_does_not_expose_request_details():
    client = GitHubClient(session=Session([requests.ConnectionError("secret-token")]))

    with pytest.raises(GitHubClientError) as captured:
        client.resolve_commit("owner/repo")

    assert str(captured.value) == "GitHub request failed"


@override_settings(
    COMMUNITY_BASE={
        "CONTENT_SYNC_GITHUB_APP_ID": "123",
        "CONTENT_SYNC_GITHUB_INSTALLATION_ID": "456",
        "CONTENT_SYNC_GITHUB_PRIVATE_KEY": "private-key",
    }
)
def test_private_checkout_uses_installation_token(monkeypatch):
    monkeypatch.setattr(
        "community_base.content_sync.github.jwt.encode", lambda *args, **kwargs: "app"
    )
    session = Session(
        [
            Response(json_data={"token": "installation-token"}),
            Response(json_data={"sha": SHA}),
        ]
    )
    client = GitHubClient(session=session)

    assert client.resolve_commit("owner/repo", private=True) == SHA
    assert session.calls[0][1].endswith("/app/installations/456/access_tokens")
    assert session.calls[1][2]["headers"]["Authorization"] == "Bearer installation-token"


@override_settings(COMMUNITY_BASE={})
def test_repository_name_must_be_owner_and_name():
    client = GitHubClient(session=Session([]))

    with pytest.raises(GitHubClientError, match="repository name"):
        client.resolve_commit("https://github.com/owner/repo")
