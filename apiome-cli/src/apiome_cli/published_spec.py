"""Shared core for ``apiome schema <format> <tenant>/<project>/<version>`` downloads (CLI 9.x).

The ``schema`` download commands fetch a **published** version's generated document from the
public spec routes (``/v1/arazzo/...`` today; the OpenAPI and JSON Schema routes later) by its
``tenant/project/version`` slugs. This module holds everything those commands share, so each
command only names its route:

* :func:`parse_published_ref` / :func:`parse_project_ref` — split and validate the
  ``tenant/project/version`` (or ``tenant/project``) argument;
* :func:`parse_serialization` — the ``--format json|yaml`` value;
* :func:`normalize_expected_sha256` / :func:`sha256_hex` — the ``--expect-sha256`` check;
* :func:`fetch_published_document` — GET the route, with ``Accept`` set for YAML;
* :func:`fetch_published_openapi` — GET ``/v1/schema/...`` parsed, for ``schema diff``.

The document bytes are kept exactly as the server sent them, so the checksum is over the bytes
that are written.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import typer

from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.client.spec_download import SpecDownloadResult, SpecFormat, SpecSerialization
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.import_.yaml_load import safe_load

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


def parse_project_ref(text: str) -> tuple[str, str]:
    """Parse ``tenant/project`` (``schema diff``'s first argument) into its two slugs.

    Raises:
        ValueError: When the text does not have exactly two non-empty ``/``-separated parts.
    """
    parts = [part.strip() for part in text.strip().split("/")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"expected <tenant>/<project>, got {text!r}")
    return parts[0], parts[1]


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


def _parse_document(body: bytes) -> object:
    """Parse a served spec as JSON, falling back to YAML (a frozen snapshot may be YAML)."""
    try:
        return json.loads(body)
    except ValueError:
        return safe_load(body)


def fetch_published_openapi(client: RestClient, ref: PublishedRef) -> tuple[PublishedRef, dict[str, Any]]:
    """GET ``/v1/schema/{tenant}/{project}/{version}`` and parse it into a mapping.

    The public route matches the version label exactly. A label typed with a leading ``v``
    (``v2.1.0``) that is not found is retried once without it (``2.1.0``), because labels are
    usually stored bare.

    Args:
        client: REST client (sends ``X-API-Key`` when configured, for private versions).
        ref: The published version.

    Returns:
        The ref that matched (the ``v`` stripped if the retry was used) and the document.
        Exits 2 on a 4xx and 1 on a 5xx (:func:`exit_on_api_error`), or 1 when the body is not
        an OpenAPI mapping.
    """
    headers = {"Accept": "application/json"}
    response = client.get_raw(published_document_path("schema", ref), headers=headers)
    if response.status_code == 404 and ref.version[:1] in ("v", "V") and len(ref.version) > 1:
        bare = PublishedRef(ref.tenant, ref.project, ref.version[1:])
        retry = client.get_raw(published_document_path("schema", bare), headers=headers)
        if retry.status_code != 404:
            ref, response = bare, retry
    exit_on_api_error(response)
    try:
        document = _parse_document(response.content)
    except (ValueError, UnicodeDecodeError) as exc:
        typer.echo(f"{ref.label()}: the server did not return a readable spec ({exc}).", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    if not isinstance(document, dict):
        typer.echo(f"{ref.label()}: the server did not return an OpenAPI document.", err=True)
        raise typer.Exit(EXIT_ERROR)
    return ref, document
