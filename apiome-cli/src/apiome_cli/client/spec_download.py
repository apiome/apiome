"""Download reconstructed specs from apiome-rest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from apiome_cli.client.browse_scope import (
    BrowseExportScope,
    build_arazzo_export_path,
    build_schema_export_path,
)
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient

SpecFormat = Literal["openapi", "arazzo"]
SpecSerialization = Literal["json", "yaml"]


@dataclass(frozen=True)
class SpecDownloadResult:
    """Reconstructed OpenAPI or Arazzo document bytes and response metadata."""

    body: bytes
    content_type: str | None
    etag: str | None
    format: SpecFormat
    serialization: SpecSerialization


def _build_spec_query(*, serialization: SpecSerialization) -> str:
    if serialization == "yaml":
        return urlencode({"accept": "yaml"})
    return ""


def _export_path(scope: BrowseExportScope, *, spec_format: SpecFormat) -> str:
    if spec_format == "arazzo":
        return build_arazzo_export_path(scope)
    return build_schema_export_path(scope)


def fetch_browse_spec(
    client: RestClient,
    scope: BrowseExportScope,
    *,
    spec_format: SpecFormat,
    serialization: SpecSerialization,
) -> SpecDownloadResult:
    """Fetch a reconstructed spec from published export routes."""
    path = _export_path(scope, spec_format=spec_format)
    query = _build_spec_query(serialization=serialization)
    headers: dict[str, str] = {}
    if serialization == "yaml":
        headers["Accept"] = "application/yaml"
    request_path = f"{path}?{query}" if query else path
    response = client.get_raw(request_path, headers=headers)
    exit_on_api_error(response)
    return SpecDownloadResult(
        body=response.content,
        content_type=response.headers.get("Content-Type"),
        etag=response.headers.get("ETag"),
        format=spec_format,
        serialization=serialization,
    )
