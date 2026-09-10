"""Uploading a distribution to npm and PyPI — SDK-4.1 (#4495).

The one place a tenant's registry token leaves the process. Everything above this module works in
terms of a built :class:`~app.sdk_distribution.Distribution` and a
:class:`~app.sdk_registry_credentials.ResolvedCredential`; this module turns that pair into an
HTTP request the registry accepts, and turns the answer back into a receipt.

**Two protocols, deliberately hand-written.** Neither `npm` nor `twine` is invoked: shelling out
would mean writing the token to a `.npmrc`/`.pypirc` on disk, inheriting a package manager's own
network and cache behaviour, and parsing human output to find out what happened. Both registries
accept a single, well-specified HTTP request instead —

* **npm**: ``PUT {registry}/{name}`` with a *packument* body carrying the package metadata, the
  ``dist-tags``, and the tarball base64-encoded in ``_attachments``. Bearer token.
* **PyPI**: ``POST {upload endpoint}`` as ``multipart/form-data`` with ``:action=file_upload``,
  the core-metadata fields, and the sdist as the ``content`` part. HTTP Basic as ``__token__``.

**Every request is SSRF-guarded.** The registry URL is tenant-configured, so it is fetched through
:func:`app.ssrf_guard.build_guarded_client`, which re-validates every hop including redirects. A
private-network "registry" is refused rather than handed a credential.

**Republishing is not an error.** Both registries answer 409 (npm may also answer 403 with a
"cannot publish over" message) when the version already exists. That is reported as
:data:`STATUS_ALREADY_PUBLISHED` rather than as a failure: the acceptance criterion is that the
version mapping is deterministic, and a deterministic mapping re-run is *expected* to find its own
earlier upload. The caller decides whether that is worth surfacing as an error.

**Nothing that leaves here contains the token.** Registry error bodies are outside our control, so
every message is passed through :func:`app.sdk_registry_credentials.redact_secrets` before it is
returned, and the ``Authorization`` header is never logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import httpx

from .sdk_distribution import Distribution
from .sdk_publish_version import NPM_ECOSYSTEM, PYPI_ECOSYSTEM
from .sdk_registry_credentials import ResolvedCredential, redact_secrets
from .ssrf_guard import SSRFError, build_guarded_client

logger = logging.getLogger(__name__)

__all__ = [
    "PUBLISH_TIMEOUT_SECONDS",
    "STATUS_ALREADY_PUBLISHED",
    "STATUS_PUBLISHED",
    "ClientFactory",
    "PublishReceipt",
    "RegistryUploadError",
    "npm_packument",
    "publish_distribution",
    "pypi_upload_fields",
]

#: An upload is a single request carrying a whole tarball, so the timeout is generous — but it is
#: bounded, because a publish holds a request thread and a registry that never answers must not.
PUBLISH_TIMEOUT_SECONDS = 120.0

#: The receipt status when the registry accepted the upload.
STATUS_PUBLISHED = "published"

#: The receipt status when the registry already had this exact version.
STATUS_ALREADY_PUBLISHED = "already_published"

#: How an :class:`httpx.Client` is obtained. Injected so tests exercise the request bodies these
#: functions build without a network, and so one call site owns the SSRF policy.
ClientFactory = Callable[[], httpx.Client]

#: Status codes that mean "this version is already here".
_CONFLICT_STATUSES = frozenset({409})

#: How much of a registry's error body is kept. Enough to carry the registry's own explanation,
#: bounded because some registries answer an error with an HTML page.
_ERROR_BODY_MAX_CHARS = 800


class RegistryUploadError(RuntimeError):
    """Raised when a distribution could not be published.

    Attributes:
        http_status: The registry's status code, when there was a response.
        retryable: Whether trying again unchanged could plausibly succeed — a timeout or a 5xx,
            but not a 401 or a rejected version.
    """

    def __init__(
        self, message: str, *, http_status: Optional[int] = None, retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retryable = retryable


@dataclass(frozen=True)
class PublishReceipt:
    """What the registry said.

    Attributes:
        status: :data:`STATUS_PUBLISHED` or :data:`STATUS_ALREADY_PUBLISHED`.
        http_status: The registry's status code.
        registry_url: The endpoint that was written to.
        package_name: The published name.
        package_version: The published version.
        message: A short, secret-free description for the run log.
        detail: Anything else worth recording (the registry's own ``rev``, a location header).
    """

    status: str
    http_status: int
    registry_url: str
    package_name: str
    package_version: str
    message: str
    detail: Dict[str, Any] = field(default_factory=dict)


def _default_client_factory() -> httpx.Client:
    """Build the SSRF-guarded client every upload goes through.

    Returns:
        A client whose every request — including redirects — is re-validated against the SSRF
        policy, so a tenant cannot point a registry URL at an internal address and be handed a
        credential.
    """
    return build_guarded_client(timeout=PUBLISH_TIMEOUT_SECONDS, follow_redirects=False)


def _truncate(text: str) -> str:
    """Bound a registry's response body for storage in a run log."""
    body = (text or "").strip()
    if len(body) <= _ERROR_BODY_MAX_CHARS:
        return body
    return body[: _ERROR_BODY_MAX_CHARS - 1].rstrip() + "…"


def _integrity(content: bytes) -> str:
    """Return the Subresource-Integrity string npm records for a tarball.

    Args:
        content: The tarball bytes.

    Returns:
        ``sha512-<base64>`` — the form npm's own client publishes and its registry verifies.
    """
    return "sha512-" + base64.b64encode(hashlib.sha512(content).digest()).decode("ascii")


def npm_packument(distribution: Distribution, registry_url: str) -> Dict[str, Any]:
    """Build the npm publish body for a distribution.

    The document npm's own client sends: the package's metadata at the top level, the full
    ``package.json`` for this one version under ``versions``, and the tarball base64-encoded under
    ``_attachments``.

    Args:
        distribution: The built npm distribution.
        registry_url: The registry root, used to form the ``dist.tarball`` URL the registry
            rewrites anyway but expects to be present.

    Returns:
        The JSON-serialisable body.
    """
    name = distribution.package_name
    version = distribution.package_version
    encoded_name = quote(name, safe="@")
    manifest: Dict[str, Any] = dict(distribution.metadata)
    manifest["_id"] = f"{name}@{version}"
    manifest["dist"] = {
        # npm still records a SHA-1 "shasum" alongside the modern integrity string.
        "shasum": hashlib.sha1(distribution.content).hexdigest(),  # noqa: S324 - registry format
        "integrity": _integrity(distribution.content),
        "tarball": f"{registry_url.rstrip('/')}/{encoded_name}/-/{distribution.filename}",
    }
    return {
        "_id": name,
        "name": name,
        "description": manifest.get("description", ""),
        # A scoped package is private by default; publishing one without this fails with a
        # paid-plan error that has nothing to do with the caller's plan.
        "access": "public",
        "dist-tags": {"latest": version},
        "versions": {version: manifest},
        "readme": next(
            (item.text for item in distribution.files if item.subject == "readme"), ""
        ),
        "_attachments": {
            distribution.filename: {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(distribution.content).decode("ascii"),
                "length": distribution.content_length,
            }
        },
    }


def pypi_upload_fields(distribution: Distribution) -> Dict[str, Any]:
    """Build the PyPI legacy-upload form fields for a distribution.

    Args:
        distribution: The built PyPI distribution.

    Returns:
        Field name → value. ``project_urls`` maps to a *list*, which the form encoder repeats once
        per entry — the legacy upload API takes multi-valued fields by repetition, and that is how
        provenance rides into the published metadata.
    """
    metadata = distribution.metadata
    description = next(
        (item.text for item in distribution.files if item.subject == "readme"), ""
    )
    return {
        ":action": "file_upload",
        "protocol_version": "1",
        "metadata_version": str(metadata.get("metadata_version", "2.1")),
        "name": distribution.package_name,
        "version": distribution.package_version,
        "filetype": "sdist",
        "pyversion": "source",
        "summary": str(metadata.get("summary", "")),
        "description": description,
        "description_content_type": str(metadata.get("description_content_type", "")),
        "keywords": str(metadata.get("keywords", "")),
        "requires_python": str(metadata.get("requires_python", "")),
        "sha256_digest": distribution.sha256,
        # Warehouse still accepts (and some mirrors still require) the legacy MD5 field. It is a
        # transport checksum next to the SHA-256, never a security claim.
        "md5_digest": hashlib.md5(distribution.content).hexdigest(),  # noqa: S324 - form field
        "project_urls": list(metadata.get("project_urls", [])),
    }


def _publish_npm(
    distribution: Distribution, credential: ResolvedCredential, client: httpx.Client
) -> httpx.Response:
    """Send the npm publish request.

    Args:
        distribution: The built npm distribution.
        credential: The token and registry to publish with.
        client: The guarded HTTP client.

    Returns:
        The raw response, for :func:`_receipt_from` to interpret.
    """
    url = f"{credential.registry_url.rstrip('/')}/{quote(distribution.package_name, safe='@')}"
    body = npm_packument(distribution, credential.registry_url)
    return client.put(
        url,
        content=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {credential.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )


def _publish_pypi(
    distribution: Distribution, credential: ResolvedCredential, client: httpx.Client
) -> httpx.Response:
    """Send the PyPI upload request.

    Args:
        distribution: The built PyPI distribution.
        credential: The token and upload endpoint to publish with.
        client: The guarded HTTP client.

    Returns:
        The raw response.
    """
    return client.post(
        credential.registry_url,
        data=pypi_upload_fields(distribution),
        files={
            "content": (
                distribution.filename,
                distribution.content,
                "application/octet-stream",
            )
        },
        # PyPI's API tokens authenticate as the literal user ``__token__``.
        auth=("__token__", credential.token),
        headers={"Accept": "application/json"},
    )


def _receipt_from(
    response: httpx.Response, distribution: Distribution, credential: ResolvedCredential
) -> PublishReceipt:
    """Interpret a registry response, or raise.

    Args:
        response: What the registry answered.
        distribution: What was uploaded.
        credential: The credential used — its token is the secret redacted from any message.

    Returns:
        The receipt, for an accepted upload or an already-present version.

    Raises:
        RegistryUploadError: For every other answer. The message carries the registry's own
            explanation with the token redacted, and ``retryable`` says whether repeating the
            request unchanged could plausibly work.
    """
    body = redact_secrets(_truncate(response.text), [credential.token])
    coordinates = f"{distribution.package_name}@{distribution.package_version}"

    if response.is_success:
        return PublishReceipt(
            status=STATUS_PUBLISHED,
            http_status=response.status_code,
            registry_url=credential.registry_url,
            package_name=distribution.package_name,
            package_version=distribution.package_version,
            message=f"Published {coordinates} to {credential.registry_url}.",
            detail={"contentLength": distribution.content_length},
        )

    already = response.status_code in _CONFLICT_STATUSES or (
        response.status_code == 403 and "cannot publish over" in body.lower()
    )
    if already:
        return PublishReceipt(
            status=STATUS_ALREADY_PUBLISHED,
            http_status=response.status_code,
            registry_url=credential.registry_url,
            package_name=distribution.package_name,
            package_version=distribution.package_version,
            message=f"{coordinates} is already present on {credential.registry_url}.",
            detail={"registryMessage": body},
        )

    if response.status_code in (401, 403):
        raise RegistryUploadError(
            f"The registry rejected the credential for {coordinates} "
            f"(HTTP {response.status_code}): {body or 'no detail'}",
            http_status=response.status_code,
            retryable=False,
        )
    raise RegistryUploadError(
        f"The registry refused {coordinates} (HTTP {response.status_code}): {body or 'no detail'}",
        http_status=response.status_code,
        retryable=response.status_code >= 500 or response.status_code == 429,
    )


def publish_distribution(
    distribution: Distribution,
    credential: ResolvedCredential,
    *,
    client_factory: Optional[ClientFactory] = None,
) -> PublishReceipt:
    """Upload one distribution to its registry.

    Args:
        distribution: The built archive and its metadata.
        credential: The token and registry endpoint to publish with.
        client_factory: How to obtain the HTTP client. Defaults to the SSRF-guarded one; injected
            by tests so the request bodies are exercised without a network.

    Returns:
        The :class:`PublishReceipt`.

    Raises:
        RegistryUploadError: When the upload was refused, the registry could not be reached, the
            URL is not one this deployment may fetch, or the ecosystem has no transport.
    """
    if distribution.ecosystem == NPM_ECOSYSTEM:
        send = _publish_npm
    elif distribution.ecosystem == PYPI_ECOSYSTEM:
        send = _publish_pypi
    else:
        raise RegistryUploadError(
            f"No publish transport for ecosystem {distribution.ecosystem!r}."
        )

    factory = client_factory or _default_client_factory
    try:
        with factory() as client:
            response = send(distribution, credential, client)
    except SSRFError as exc:
        raise RegistryUploadError(
            f"The registry URL is not one this deployment may publish to: {exc}",
            retryable=False,
        ) from exc
    except httpx.TimeoutException as exc:
        raise RegistryUploadError(
            f"The registry did not answer within {PUBLISH_TIMEOUT_SECONDS:.0f}s.", retryable=True
        ) from exc
    except httpx.HTTPError as exc:
        # httpx messages quote the URL, never the Authorization header, but redaction is cheap and
        # this string is about to be persisted in a run log.
        raise RegistryUploadError(
            f"The registry could not be reached: "
            f"{redact_secrets(str(exc), [credential.token])}",
            retryable=True,
        ) from exc

    return _receipt_from(response, distribution, credential)
