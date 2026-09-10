"""Uploading to npm and PyPI — SDK-4.1 (#4495).

:mod:`app.sdk_registry_client` is the only place a tenant's token leaves the process, so what is
asserted here is the *request* each registry gets, the way each answer is interpreted, and — for
every path through the module — that nothing it returns or raises carries the credential.

No network: an ``httpx.Client`` backed by a ``MockTransport`` is injected, which exercises the real
request-building code (headers, multipart encoding, JSON body) against a scripted registry.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Optional

import httpx
import pytest
from test_sdk_distribution import _BRANDING, _COORDS, _SPEC, _api

from app.sdk_distribution import build_distribution
from app.sdk_registry_client import (
    STATUS_ALREADY_PUBLISHED,
    STATUS_PUBLISHED,
    RegistryUploadError,
    npm_packument,
    publish_distribution,
    pypi_upload_fields,
)
from app.sdk_registry_credentials import REDACTION_MARKER, ResolvedCredential
from app.ssrf_guard import SSRFError

_TOKEN = "npm_supersecrettokenvalue"


def _distribution(ecosystem: str = "npm"):
    """A built distribution to upload."""
    return build_distribution(
        _api(),
        ecosystem=ecosystem,
        coordinates=_COORDS,
        branding=_BRANDING,
        package_name=_BRANDING.package_names[ecosystem],
        package_version="1.4.3",
        release_series="1.4",
        regen_counter=3,
        source_text=_SPEC,
        source_format="openapi-3.1",
    )


def _credential(ecosystem: str = "npm", url: Optional[str] = None) -> ResolvedCredential:
    """The credential to publish with."""
    default = (
        "https://registry.npmjs.org" if ecosystem == "npm" else "https://upload.pypi.org/legacy/"
    )
    return ResolvedCredential(
        ecosystem=ecosystem, token=_TOKEN, registry_url=url or default, scope="tenant"
    )


def _client(handler):
    """A client factory backed by a scripted transport."""
    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------------------------
# npm request
# --------------------------------------------------------------------------------------------
def test_the_npm_body_is_a_packument_with_the_tarball_attached():
    dist = _distribution("npm")
    body = npm_packument(dist, "https://registry.npmjs.org")
    assert body["name"] == "@acme/widgets-sdk"
    assert body["dist-tags"] == {"latest": "1.4.3"}
    assert body["access"] == "public", "a scoped package published without this fails confusingly"
    version = body["versions"]["1.4.3"]
    assert version["_id"] == "@acme/widgets-sdk@1.4.3"
    assert version["dist"]["integrity"].startswith("sha512-")
    attachment = body["_attachments"][dist.filename]
    assert base64.b64decode(attachment["data"]) == dist.content
    assert attachment["length"] == dist.content_length


def test_npm_publishes_with_a_bearer_token_to_the_encoded_package_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(201, json={"ok": True})

    receipt = publish_distribution(
        _distribution("npm"), _credential("npm"), client_factory=_client(handler)
    )
    assert seen["method"] == "PUT"
    # The scope's slash is percent-encoded; npm's own client does the same.
    assert seen["url"] == "https://registry.npmjs.org/@acme%2Fwidgets-sdk"
    assert seen["auth"] == f"Bearer {_TOKEN}"
    assert receipt.status == STATUS_PUBLISHED


# --------------------------------------------------------------------------------------------
# PyPI request
# --------------------------------------------------------------------------------------------
def test_the_pypi_form_carries_the_metadata_and_the_provenance():
    dist = _distribution("pypi")
    fields = pypi_upload_fields(dist)
    assert fields[":action"] == "file_upload"
    assert fields["filetype"] == "sdist"
    assert fields["name"] == "acme-widgets"
    assert fields["version"] == "1.4.3"
    assert fields["sha256_digest"] == hashlib.sha256(dist.content).hexdigest()
    # A list value, so the form encoder repeats the field — how provenance reaches PyPI.
    assert any("versionRecordId" in url for url in fields["project_urls"])


def test_pypi_publishes_as_the_token_user_with_the_sdist_attached():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = request.content
        return httpx.Response(200, text="OK")

    dist = _distribution("pypi")
    receipt = publish_distribution(dist, _credential("pypi"), client_factory=_client(handler))
    assert seen["method"] == "POST"
    assert seen["url"] == "https://upload.pypi.org/legacy/"
    expected = base64.b64encode(f"__token__:{_TOKEN}".encode()).decode()
    assert seen["auth"] == f"Basic {expected}"
    assert dist.filename.encode() in seen["body"]
    # ``project_urls`` is a multi-valued field, repeated once per entry by the form encoder —
    # which is how provenance reaches the published PyPI metadata.
    assert seen["body"].count(b'name="project_urls"') > 1
    assert b"versionRecordId" in seen["body"]
    assert receipt.status == STATUS_PUBLISHED


# --------------------------------------------------------------------------------------------
# Interpreting the answer
# --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("status", [200, 201])
def test_a_success_is_a_published_receipt(status):
    receipt = publish_distribution(
        _distribution("npm"),
        _credential(),
        client_factory=_client(lambda request: httpx.Response(status, json={})),
    )
    assert receipt.status == STATUS_PUBLISHED
    assert receipt.package_version == "1.4.3"
    assert "@acme/widgets-sdk@1.4.3" in receipt.message


def test_a_conflict_is_already_published_not_a_failure():
    """A deterministic mapping re-run is *expected* to find its own earlier upload."""
    receipt = publish_distribution(
        _distribution("npm"),
        _credential(),
        client_factory=_client(
            lambda request: httpx.Response(409, json={"error": "version already exists"})
        ),
    )
    assert receipt.status == STATUS_ALREADY_PUBLISHED


def test_npms_cannot_publish_over_403_is_also_already_published():
    receipt = publish_distribution(
        _distribution("npm"),
        _credential(),
        client_factory=_client(
            lambda request: httpx.Response(
                403, json={"error": "You cannot publish over the previously published versions"}
            )
        ),
    )
    assert receipt.status == STATUS_ALREADY_PUBLISHED


def test_a_rejected_credential_is_a_non_retryable_error():
    with pytest.raises(RegistryUploadError) as exc:
        publish_distribution(
            _distribution("npm"),
            _credential(),
            client_factory=_client(lambda request: httpx.Response(401, text="unauthorized")),
        )
    assert exc.value.http_status == 401
    assert exc.value.retryable is False


@pytest.mark.parametrize("status, retryable", [(500, True), (429, True), (400, False)])
def test_retryability_follows_the_status(status, retryable):
    with pytest.raises(RegistryUploadError) as exc:
        publish_distribution(
            _distribution("npm"),
            _credential(),
            client_factory=_client(lambda request: httpx.Response(status, text="nope")),
        )
    assert exc.value.retryable is retryable


def test_a_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(RegistryUploadError, match="did not answer") as exc:
        publish_distribution(_distribution("npm"), _credential(), client_factory=_client(handler))
    assert exc.value.retryable is True


def test_an_ssrf_refusal_is_reported_as_a_refused_registry():
    def factory():
        raise SSRFError("host resolves to a private address")

    with pytest.raises(RegistryUploadError, match="not one this deployment may publish to"):
        publish_distribution(_distribution("npm"), _credential(), client_factory=factory)


def test_an_ecosystem_with_no_transport_is_refused():
    dist = _distribution("npm")
    broken = dist.__class__(**{**dist.__dict__, "ecosystem": "gomod"})
    with pytest.raises(RegistryUploadError, match="No publish transport"):
        publish_distribution(broken, _credential(), client_factory=_client(lambda r: None))


# --------------------------------------------------------------------------------------------
# The token never comes back out
# --------------------------------------------------------------------------------------------
def test_a_registry_that_echoes_the_token_has_it_redacted():
    """Registry error bodies are outside our control, and a run log is forever."""
    body = f"invalid token {_TOKEN} for scope @acme"
    with pytest.raises(RegistryUploadError) as exc:
        publish_distribution(
            _distribution("npm"),
            _credential(),
            client_factory=_client(lambda request: httpx.Response(400, text=body)),
        )
    assert _TOKEN not in str(exc.value)
    assert REDACTION_MARKER in str(exc.value)


def test_an_already_published_receipt_is_redacted_too():
    receipt = publish_distribution(
        _distribution("npm"),
        _credential(),
        client_factory=_client(lambda request: httpx.Response(409, text=f"exists ({_TOKEN})")),
    )
    assert _TOKEN not in json.dumps(receipt.detail)


def test_a_huge_error_body_is_truncated():
    with pytest.raises(RegistryUploadError) as exc:
        publish_distribution(
            _distribution("npm"),
            _credential(),
            client_factory=_client(lambda request: httpx.Response(500, text="x" * 10_000)),
        )
    assert len(str(exc.value)) < 1_200
