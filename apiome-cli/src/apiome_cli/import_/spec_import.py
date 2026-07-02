"""Build and submit ``POST /v1/tenants/{tenant_slug}/imports`` requests."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from apiome_cli.client import api_paths
from apiome_cli.client.http import RestClient
from apiome_cli.extract.openapi_info import extract_info_metadata


def infer_source_kind(document: dict[str, Any], *, filename: str | None = None) -> str:
    """Map an OpenAPI/Swagger document to REST ``source_kind``."""
    if isinstance(document.get("swagger"), str):
        return "swagger-2"
    openapi = document.get("openapi")
    if isinstance(openapi, str):
        if openapi.startswith("3."):
            return "openapi-3"
    if filename and filename.lower().endswith((".yaml", ".yml", ".json")):
        return "openapi-3"
    return "openapi-3"


def build_spec_import_metadata(
    document: dict[str, Any],
    *,
    source_kind: str,
    project_name: str | None = None,
    project_slug: str | None = None,
    version: str | None = None,
    existing_project_id: str | None = None,
    dry_run: bool = False,
    skip_duplicate_versions: bool = False,
) -> dict[str, Any]:
    """Build ``SpecImportStartMetadata`` from CLI overrides and document ``info``."""
    info = extract_info_metadata(document)
    name = (project_name or info.name or "imported-project").strip()
    slug = (project_slug or info.project_slug).strip()
    version_id = (version or info.version or "0.0.0").strip()
    metadata: dict[str, Any] = {
        "source_kind": source_kind,
        "project": {"name": name, "slug": slug},
        "version": {"version_id": version_id},
        "options": {
            "dry_run": dry_run,
            "skip_duplicate_versions": skip_duplicate_versions,
        },
    }
    if existing_project_id:
        metadata["existing_project_id"] = existing_project_id
    return metadata


def build_spec_import_json_body(
    document_bytes: bytes,
    metadata: dict[str, Any],
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Build ``SpecImportStartJsonRequest``."""
    body: dict[str, Any] = {
        "metadata": metadata,
        "document_base64": base64.b64encode(document_bytes).decode("ascii"),
    }
    if filename:
        body["filename"] = filename
    if content_type:
        body["content_type"] = content_type
    return body


def document_bytes_from_spec(spec: dict[str, Any], *, filename: str | None = None) -> bytes:
    """Serialize a parsed spec to **JSON** bytes for upload (never YAML).

    The import worker parses the uploaded document with a strict JS YAML reader. Re-serializing a
    parsed spec back to YAML can emit constructs that reader rejects — e.g. a description line that
    begins ``- **field**:`` round-trips into an ambiguous block sequence / alias ("A block sequence
    may not be used as an implicit map key") — even when the *original* document parsed cleanly. JSON
    is unambiguous, is itself valid YAML, and round-trips through both the JS ``JSON.parse`` and YAML
    readers. ``default=str`` coerces any non-JSON scalars a YAML loader may have produced (e.g. bare
    dates) so serialization never fails. ``filename`` is accepted for caller convenience but no longer
    affects the format.
    """
    _ = filename
    return json.dumps(spec, indent=2, default=str).encode("utf-8")


def post_spec_import_json(
    client: RestClient,
    tenant_slug: str,
    body: dict[str, Any],
) -> Any:
    return client.post(api_paths.tenant_imports(tenant_slug), json=body)


def post_spec_import_multipart(
    client: RestClient,
    tenant_slug: str,
    *,
    metadata: dict[str, Any],
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/json",
) -> Any:
    # The document is always uploaded as JSON (see document_bytes_from_spec), so the part's content
    # type is application/json unless a caller explicitly overrides it.
    return client.post(
        api_paths.tenant_imports_upload(tenant_slug),
        data={"metadata": json.dumps(metadata)},
        files={"file": (filename, file_bytes, content_type)},
    )


def source_basename(path: str) -> str:
    if path.startswith(("http://", "https://")):
        return Path(path.split("?", 1)[0]).name
    return Path(path).name
