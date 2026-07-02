"""Upload OpenAPI documents to apiome-rest and resolve import results."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from re import Pattern, compile as compile_regex
from typing import Any, Literal
from uuid import UUID

import httpx
import typer

from apiome_cli.client.http import RestClient
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.extract.slug import PROJECT_SLUG_RE, VERSION_SLUG_RE
from apiome_cli.import_.jobs import DEFAULT_POLL_INTERVAL, wait_for_import_job
# OpenAPI ``info`` extensions carrying CLI slug overrides in the import request body.
X_APIOME_PROJECT_SLUG = "x-apiome-project-slug"
X_APIOME_VERSION_SLUG = "x-apiome-version-slug"
X_APIOME_PROJECT_NAME_FIELD = "x-apiome-project-name-field"

_MAX_SLUG_LENGTH = 255
_MAX_PROJECT_NAME_FIELD_LENGTH = 255
_PROJECT_NAME_FIELD_RE = compile_regex(r"^[#]?[/a-zA-Z0-9._~-]+$")


@dataclass(frozen=True)
class ImportResolution:
    """Import response payload with an explicit outcome kind."""

    kind: Literal["completed", "accepted"]
    payload: dict[str, Any]


def _normalize_slug_override(
    value: str,
    *,
    label: str,
    pattern: Pattern[str],
) -> str:
    """Validate a user-supplied slug override against DB ``CHECK`` rules."""
    trimmed = value.strip()
    if not trimmed:
        msg = f"{label} cannot be empty."
        raise ValueError(msg)
    if len(trimmed) > _MAX_SLUG_LENGTH:
        msg = f"{label} exceeds maximum length of {_MAX_SLUG_LENGTH} characters."
        raise ValueError(msg)
    if not pattern.fullmatch(trimmed):
        msg = (
            f"{label} {trimmed!r} is invalid; "
            f"must satisfy the database slug pattern."
        )
        raise ValueError(msg)
    return trimmed


def _normalize_project_name_field_override(value: str) -> str:
    """Validate a user-supplied project-name field path."""
    trimmed = value.strip()
    if not trimmed:
        msg = "Project name field cannot be empty."
        raise ValueError(msg)
    if len(trimmed) > _MAX_PROJECT_NAME_FIELD_LENGTH:
        msg = (
            "Project name field exceeds maximum length of "
            f"{_MAX_PROJECT_NAME_FIELD_LENGTH} characters."
        )
        raise ValueError(msg)
    if not _PROJECT_NAME_FIELD_RE.fullmatch(trimmed):
        msg = (
            f"Project name field {trimmed!r} is invalid; "
            "must use dot paths or JSON Pointers such as info.summary or #/info/summary."
        )
        raise ValueError(msg)
    return trimmed


def apply_info_overrides(
    spec: dict[str, Any],
    *,
    project_name: str | None = None,
    version: str | None = None,
    project_slug: str | None = None,
    version_slug: str | None = None,
    project_name_field: str | None = None,
) -> dict[str, Any]:
    """Return *spec* with CLI overrides applied to the ``info`` block.

    Name and version overrides update ``info.title`` and ``info.version``.
    Slug and project-name field overrides are stored as ``x-apiome-*``
    extensions on ``info`` so they are included in the ``POST /imports/openapi``
    JSON body and honoured by the REST importer.

    When no override is set, returns the original mapping without copying.
    """
    if (
        project_name is None
        and version is None
        and project_slug is None
        and version_slug is None
        and project_name_field is None
    ):
        return spec

    updated = copy.deepcopy(spec)
    info = updated.get("info")
    if not isinstance(info, dict):
        info = {}
        updated["info"] = info
    if project_name is not None:
        info["title"] = project_name
    if version is not None:
        info["version"] = version
    if project_slug is not None:
        info[X_APIOME_PROJECT_SLUG] = _normalize_slug_override(
            project_slug,
            label="Project slug",
            pattern=PROJECT_SLUG_RE,
        )
    if version_slug is not None:
        info[X_APIOME_VERSION_SLUG] = _normalize_slug_override(
            version_slug,
            label="Version slug",
            pattern=VERSION_SLUG_RE,
        )
    if project_name_field is not None:
        info[X_APIOME_PROJECT_NAME_FIELD] = _normalize_project_name_field_override(
            project_name_field,
        )
    return updated


def build_arazzo_import_body(
    spec: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
    project_id: UUID | None = None,
    version_id: UUID | None = None,
    visibility: str | None = None,
    dry_run: bool = False,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Build the JSON body for ``POST /imports/arazzo``."""
    body: dict[str, Any] = {"spec": spec}
    if tenant_id is not None:
        body["tenant_id"] = str(tenant_id)
    if project_id is not None:
        body["project_id"] = str(project_id)
    if version_id is not None:
        body["version_id"] = str(version_id)
    if visibility is not None:
        body["visibility"] = visibility
    if dry_run:
        body["dry_run"] = True
    if source_url is not None:
        body["source_url"] = source_url
    return body


def build_openapi_multipart_upload(
    spec: dict[str, Any],
    *,
    filename: str,
    tenant_id: UUID | None = None,
    project_id: UUID | None = None,
    visibility: str | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]]]:
    """Build multipart form fields and file payload for ``POST /imports/openapi``."""
    import json

    raw_bytes = json.dumps(spec, indent=2).encode("utf-8")
    fields: dict[str, str] = {}
    if tenant_id is not None:
        fields["tenant_id"] = str(tenant_id)
    if project_id is not None:
        fields["project_id"] = str(project_id)
    if visibility is not None:
        fields["visibility"] = visibility
    if dry_run:
        fields["dry_run"] = "true"
    upload_name = filename or "import.json"
    if upload_name.lower().endswith((".yaml", ".yml")):
        upload_name = f"{Path(upload_name).stem}.json"
    files = {
        "file": (
            upload_name,
            raw_bytes,
            "application/json",
        )
    }
    return fields, files


def build_arazzo_multipart_upload(
    spec: dict[str, Any],
    *,
    filename: str,
    tenant_id: UUID | None = None,
    project_id: UUID | None = None,
    version_id: UUID | None = None,
    visibility: str | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]]]:
    """Build multipart form fields and file payload for ``POST /imports/arazzo``."""
    import json

    raw_bytes = json.dumps(spec, indent=2).encode("utf-8")
    fields: dict[str, str] = {}
    if tenant_id is not None:
        fields["tenant_id"] = str(tenant_id)
    if project_id is not None:
        fields["project_id"] = str(project_id)
    if version_id is not None:
        fields["version_id"] = str(version_id)
    if visibility is not None:
        fields["visibility"] = visibility
    if dry_run:
        fields["dry_run"] = "true"
    files = {
        "file": (
            filename or "import.json",
            raw_bytes,
            "application/json",
        )
    }
    return fields, files


def build_openapi_import_body(
    spec: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
    project_id: UUID | None = None,
    visibility: str | None = None,
    dry_run: bool = False,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Build the JSON body for ``POST /imports/openapi``."""
    body: dict[str, Any] = {"spec": spec}
    if tenant_id is not None:
        body["tenant_id"] = str(tenant_id)
    if project_id is not None:
        body["project_id"] = str(project_id)
    if visibility is not None:
        body["visibility"] = visibility
    if dry_run:
        body["dry_run"] = True
    if source_url is not None:
        body["source_url"] = source_url
    return body


def build_json_schema_type_import_body(
    document: dict[str, Any],
    *,
    name: str | None = None,
    dry_run: bool = False,
    source_url: str | None = None,
    system: bool | None = None,
) -> dict[str, Any]:
    """Build the JSON body for ``POST /imports/json-schema-type``."""
    body: dict[str, Any] = {"document": document}
    if name is not None:
        body["name"] = name
    if dry_run:
        body["dry_run"] = True
    if source_url is not None:
        body["source_url"] = source_url
    if system is not None:
        body["system"] = system
    return body


def build_json_schema_import_body(
    document: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
    import_type: str = "json-schema",
    as_target: str | None = None,
    name: str | None = None,
    description: str | None = None,
    project_id: UUID | None = None,
    version_id: UUID | None = None,
    link_project_property: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build the JSON body for ``POST /imports/json-schema``."""
    body: dict[str, Any] = {
        "import_type": import_type,
        "body": document,
    }
    if tenant_id is not None:
        body["tenant_id"] = str(tenant_id)
    if as_target is not None:
        body["as"] = as_target
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if project_id is not None:
        body["project_id"] = str(project_id)
    if version_id is not None:
        body["version_id"] = str(version_id)
    if link_project_property:
        body["link_project_property"] = True
    if dry_run:
        body["dry_run"] = True
    return body


def resolve_import_result(
    response: httpx.Response,
    client: RestClient,
    tenant_slug: str,
    *,
    wait: bool = True,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    timeout: float,
    no_progress: bool = False,
) -> ImportResolution:
    """Return import payload from an async spec import response (HTTP 202)."""
    if response.status_code == 202:
        accepted = response.json()
        if not isinstance(accepted, dict):
            typer.echo("Import accept response was not a JSON object.", err=True)
            raise typer.Exit(EXIT_ERROR)
        job_id = accepted.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            typer.echo("Import accept response missing job_id.", err=True)
            raise typer.Exit(EXIT_ERROR)

        if not wait:
            return ImportResolution(kind="accepted", payload=accepted)

        final_job = wait_for_import_job(
            client,
            tenant_slug,
            job_id.strip(),
            poll_interval=poll_interval,
            timeout=timeout,
            no_progress=no_progress,
        )
        result = final_job.get("result")
        summary = final_job.get("summary")
        payload: dict[str, Any]
        if isinstance(result, dict):
            payload = dict(result)
        elif isinstance(summary, dict):
            payload = dict(summary)
        else:
            payload = {"job_id": job_id.strip(), "state": final_job.get("state")}
        payload.setdefault("job_id", job_id.strip())
        return ImportResolution(kind="completed", payload=payload)

    typer.echo(
        f"Unexpected import response status {response.status_code}.",
        err=True,
    )
    raise typer.Exit(EXIT_ERROR)


def import_result_has_errors(payload: dict[str, Any]) -> bool:
    """Return True when the server reported one or more import errors."""
    errors = payload.get("errors")
    return isinstance(errors, list) and len(errors) > 0
