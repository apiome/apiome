"""Shared core for ``apiome schema <format> <tenant>/<project>/<version>`` downloads (CLI 9.x).

The ``schema`` download commands fetch a **published** version's generated document from the
public spec routes (``/v1/arazzo/...`` today; the OpenAPI and JSON Schema routes later) by its
``tenant/project/version`` slugs. This module holds everything those commands share, so each
command only names its route:

* :func:`parse_published_ref` — split and validate the ``tenant/project/version`` argument;
* :func:`parse_serialization` — the ``--format json|yaml`` value;
* :func:`normalize_expected_sha256` / :func:`sha256_hex` — the ``--expect-sha256`` check;
* :func:`fetch_published_document` — GET the route, with ``Accept`` set for YAML.

The document bytes are kept exactly as the server sent them, so the checksum is over the bytes
that are written.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import quote

from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.client.spec_download import SpecDownloadResult, SpecFormat, SpecSerialization

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True)
class PublishedRef:
    """A published version addressed by slugs (raw; quoted when a path is built).

    Attributes:
        tenant: Tenant slug.
        project: Project slug.
        version: Version label as stored (e.g. ``2.1.0``), passed through unchanged.
    """

    tenant: str
    project: str
    version: str

    def label(self) -> str:
        """Return the ref as the user typed it: ``tenant/project/version``."""
        return f"{self.tenant}/{self.project}/{self.version}"


def parse_published_ref(text: str) -> PublishedRef:
    """Parse ``tenant/project/version`` into a :class:`PublishedRef`.

    Args:
        text: The positional argument, e.g. ``acme-corp/payments-api/2.1.0``.

    Returns:
        The three slugs, whitespace-stripped.

    Raises:
        ValueError: When the text does not have exactly three non-empty ``/``-separated parts.
    """
    parts = [part.strip() for part in text.strip().split("/")]
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"expected <tenant>/<project>/<version>, got {text!r}")
    return PublishedRef(tenant=parts[0], project=parts[1], version=parts[2])


def parse_serialization(value: str) -> SpecSerialization:
    """Return ``json`` or ``yaml`` for a ``--format`` value (``yml`` accepted, any case).

    Raises:
        ValueError: For any other value.
    """
    normalized = value.strip().lower()
    if normalized == "json":
        return "json"
    if normalized in ("yaml", "yml"):
        return "yaml"
    raise ValueError(f"--format must be json or yaml, got {value!r}")


def normalize_expected_sha256(value: str) -> str:
    """Return a lowercase 64-hex digest from an ``--expect-sha256`` value.

    Accepts an optional ``sha256:`` prefix (the form the metadata line prints) and any case.

    Raises:
        ValueError: When the value is not a SHA-256 hex digest.
    """
    digest = value.strip().lower().removeprefix(_SHA256_PREFIX)
    if not _SHA256_RE.match(digest):
        raise ValueError(f"--expect-sha256 must be a 64-character hex SHA-256 digest, got {value!r}")
    return digest


def sha256_hex(body: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of *body*."""
    return hashlib.sha256(body).hexdigest()


def published_document_path(route: str, ref: PublishedRef, class_name: str | None = None) -> str:
    """Build ``/v1/{route}/{tenant}/{project}/{version}[/{class}]`` with each segment quoted.

    Args:
        route: The spec route name, e.g. ``arazzo``.
        ref: The published version.
        class_name: When set, the per-class route for that class.
    """
    segments = [ref.tenant, ref.project, ref.version]
    if class_name is not None:
        segments.append(class_name)
    return f"/v1/{route}/" + "/".join(quote(segment, safe="") for segment in segments)


def fetch_published_document(
    client: RestClient,
    path: str,
    *,
    spec_format: SpecFormat,
    serialization: SpecSerialization,
) -> SpecDownloadResult:
    """GET a published document, asking for YAML through ``Accept`` when requested.

    Args:
        client: REST client (sends ``X-API-Key`` when configured, for private versions).
        path: Route from :func:`published_document_path`.
        spec_format: Recorded in the result's metadata.
        serialization: ``yaml`` sends ``Accept: application/yaml``; ``json`` is the server default.

    Returns:
        The response bytes and headers. Exits 2 on a 4xx (unknown version or class, unpublished,
        private without a key) and 1 on a 5xx, through :func:`exit_on_api_error`.
    """
    headers = {"Accept": "application/yaml"} if serialization == "yaml" else {"Accept": "application/json"}
    response = client.get_raw(path, headers=headers)
    exit_on_api_error(response)
    return SpecDownloadResult(
        body=response.content,
        content_type=response.headers.get("Content-Type"),
        etag=response.headers.get("ETag"),
        format=spec_format,
        serialization=serialization,
    )
