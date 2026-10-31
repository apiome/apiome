"""Generic ``apiome export <format> <artifact>`` job runner (MFX-8.1).

Resolves the emitter against the registry, submits an async export job, polls to completion,
downloads the artifact, and writes a single file or unpacks a zip bundle to ``--out``.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import typer

from apiome_cli.cli_context import (
    import_timeout_from_context,
    insecure_from_context,
    json_mode_from_context,
    no_progress_from_context,
    settings_from_context,
    timeout_from_context,
)
from apiome_cli.client.browse_scope import resolve_tenant_slug
from apiome_cli.client.export_jobs import (
    download_export_job_artifact,
    filename_from_disposition,
    start_export_job,
    wait_for_export_job,
)
from apiome_cli.client.export_registry import (
    fetch_export_preview,
    fetch_export_targets,
    preview_fidelity,
    projection_snapshot_hash,
    resolve_export_target,
    unavailable_export_target_reason,
    unknown_export_target_message,
)
from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid
from apiome_cli.config import require_api_key
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_USAGE
from apiome_cli.export_output import (
    enforce_export_fidelity_gate,
    format_export_fidelity_summary,
)
from apiome_cli.export_overlays import format_overlay_summary, load_overlay_files
from apiome_cli.preflight_runner import gate_export_before_job
from apiome_cli.spec_output import SpecExportMetadata, emit_download_metadata, write_document_bytes


def _text_option_keys(options_schema: Mapping[str, Any] | None) -> set[str]:
    """The options a target's schema types as text only (``string``, optionally ``null``).

    ``--option transaction_set=810`` would parse as the number ``810``; for an option the target types as
    a string, the text the user typed is what must be sent (MFX-24.5: the X12 guide's ``transaction_set``).

    Parameters
    ----------
    options_schema:
        The target's ``options_schema`` from ``GET …/export/targets``, or ``None``.

    Returns
    -------
    set[str]
        The option keys whose every allowed type is ``string`` or ``null``.
    """
    properties = (options_schema or {}).get("properties")
    if not isinstance(properties, Mapping):
        return set()
    keys: set[str] = set()
    for key, node in properties.items():
        if not isinstance(node, Mapping):
            continue
        variants = node.get("anyOf") if isinstance(node.get("anyOf"), list) else [node]
        types = {variant.get("type") for variant in variants if isinstance(variant, Mapping)}
        if "string" in types and types <= {"string", "null"}:
            keys.add(key)
    return keys


def parse_export_options(
    option_values: Sequence[str], *, options_schema: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Parse repeatable ``--option key=value`` flags into an options bag.

    Each value is parsed as JSON when it is valid JSON (``true``, ``25``, ``["a"]``), else kept as text.
    With the target's ``options_schema``, an option it types as text only keeps the typed text even when
    it looks like JSON (``transaction_set=810`` is ``"810"``, not ``810``).
    """
    text_keys = _text_option_keys(options_schema)
    options: dict[str, Any] = {}
    for raw in option_values:
        entry = raw.strip()
        if not entry or "=" not in entry:
            typer.echo(
                f"Invalid --option {raw!r}; expected key=value (e.g. --option openapi_version=3.1).",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        key, _, value = entry.partition("=")
        key = key.strip()
        if not key:
            typer.echo(f"Invalid --option {raw!r}; key cannot be empty.", err=True)
            raise typer.Exit(EXIT_USAGE)
        value = value.strip()
        if key in text_keys:
            options[key] = value
            continue
        try:
            options[key] = json.loads(value)
        except json.JSONDecodeError:
            options[key] = value
    return options


def refuse_unavailable_target(target_key: str, targets: Sequence[Any]) -> None:
    """Stop before submitting a job to a target the registry lists as unavailable (E1-6).

    Raises:
        typer.Exit: :data:`EXIT_USAGE`, with the registry's reason, when the target is unavailable.
    """
    reason = unavailable_export_target_reason(target_key, targets)
    if reason is not None:
        typer.echo(f"Export target {target_key!r} is not available: {reason}", err=True)
        raise typer.Exit(EXIT_USAGE)


def is_zip_bundle(*, content_type: str | None, body: bytes) -> bool:
    """Return True when the download body is a zip bundle."""
    if content_type and "zip" in content_type.lower():
        return True
    return len(body) >= 2 and body[:2] == b"PK"


def _basename_from_files(files: Sequence[Mapping[str, Any]] | None) -> str | None:
    if not files:
        return None
    first = files[0]
    if not isinstance(first, Mapping):
        return None
    path = first.get("path")
    if isinstance(path, str) and path.strip():
        return Path(path).name
    return None


def _out_is_directory(out: str) -> bool:
    if out == "-":
        return False
    if out.endswith("/"):
        return True
    path = Path(out)
    if path.exists():
        return path.is_dir()
    # A path that does not exist yet without a file extension is treated as a directory intent.
    return path.suffix == ""


def bundle_member_path(root: Path, member: str) -> Path:
    """Where one bundle member is unpacked: inside ``root``, never outside it.

    The server keeps bundle paths relative (X6), but an archive is untrusted input, so a member
    that is absolute or climbs out with ``..`` ("zip slip") is refused here as well.

    Args:
        root: The resolved ``--out`` directory.
        member: The archive member name.

    Returns:
        The member's destination path.

    Raises:
        typer.Exit: ``EXIT_USAGE`` for a member that would land outside ``root``.
    """
    target = (root / member).resolve()
    if target != root and root not in target.parents:
        typer.echo(f"Refusing to unpack {member!r}: it would be written outside {root}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    return target


def write_export_artifact(
    body: bytes,
    *,
    out: str,
    content_type: str | None,
    files: Sequence[Mapping[str, Any]] | None,
    disposition_filename: str | None,
) -> tuple[int, str]:
    """Write export bytes to ``--out`` (file, directory, stdout, or ``.zip``).

    Returns ``(bytes_written, effective_output_path)``.
    """
    if is_zip_bundle(content_type=content_type, body=body):
        out_path = Path(out)
        if out_path.suffix.lower() == ".zip" and not _out_is_directory(out):
            write_document_bytes(body, out)
            return len(body), out
        if not _out_is_directory(out):
            typer.echo(
                "This export is a multi-file bundle. Use --out with a directory (or a .zip path).",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        out_path.mkdir(parents=True, exist_ok=True)
        root = out_path.resolve()
        total = 0
        with zipfile.ZipFile(BytesIO(body)) as archive:
            for member in archive.namelist():
                target = bundle_member_path(root, member)
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(member)
                target.write_bytes(data)
                total += len(data)
        return total, str(out_path)

    if _out_is_directory(out):
        filename = disposition_filename or _basename_from_files(files) or "export"
        destination = str(Path(out) / filename)
        write_document_bytes(body, destination)
        return len(body), destination

    write_document_bytes(body, out)
    return len(body), out


def _fidelity_metadata(fidelity: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(fidelity, dict):
        return None
    summary = fidelity.get("summary")
    if not isinstance(summary, dict):
        return None
    payload: dict[str, object] = {"status": summary.get("tier")}
    for key in ("preserved_percent", "dropped", "approximated", "synthesized"):
        if key in summary:
            payload[key] = summary[key]
    return payload


def run_generic_export(
    ctx: typer.Context,
    *,
    target_format: str,
    artifact: str,
    version: str | None,
    out: str | None,
    option_values: Sequence[str],
    force: bool,
    confirm: bool,
    poll_interval: float,
    export_timeout_override: float | None,
    min_grade: str | None = None,
    fail_on: str | None = None,
    overlay_paths: Sequence[str] = (),
    tenant_override: str | None = None,
) -> None:
    """Resolve ``target_format``, run the async export job, and write the artifact.

    When ``--min-grade`` / ``--fail-on`` are supplied the export is pre-flighted first
    (IXH-2.6) and a blocking verdict stops the run **before** the job is submitted, so a
    gated pipeline never leaves a half-finished export job behind.

    ``overlay_paths`` (``--overlay``, GVM-4.2) are applied by the job, in order, to the version's
    OpenAPI document before it is exported. The pre-submit preview cannot see them, so an
    overlaid job is not pinned to that preview's snapshot; the job's own snapshot is reported.
    ``tenant_override`` is ``--tenant`` where the calling command has one (``export openapi``).
    """
    settings = settings_from_context(ctx)
    require_api_key(settings)

    if out is None or not out.strip():
        typer.echo("--out is required (file path, directory, '-' for stdout, or .zip).", err=True)
        raise typer.Exit(EXIT_USAGE)
    out = out.strip()

    client = RestClient(
        settings,
        timeout=timeout_from_context(ctx),
        verify=not insecure_from_context(ctx),
    )
    tenant_slug = resolve_tenant_slug(settings, client, tenant_override=tenant_override)

    project_id = resolve_project_uuid(client, tenant_slug, artifact)
    targets_response = fetch_export_targets(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
    )
    targets = targets_response.get("targets")
    if not isinstance(targets, list):
        typer.echo("Export targets response was missing a targets list.", err=True)
        raise typer.Exit(EXIT_ERROR)

    try:
        target_key = resolve_export_target(target_format, targets)
    except ValueError:
        typer.echo(unknown_export_target_message(target_format, targets), err=True)
        raise typer.Exit(EXIT_USAGE) from None
    refuse_unavailable_target(target_key, targets)

    gate_export_before_job(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
        targets=[target_key],
        min_grade=min_grade,
        fail_on=fail_on,
    )

    target_entry = next(
        (entry for entry in targets
         if isinstance(entry, Mapping) and isinstance(entry.get("descriptor"), Mapping)
         and entry["descriptor"].get("key") == target_key),
        None,
    )
    options = parse_export_options(
        option_values,
        options_schema=target_entry.get("options_schema") if target_entry else None,
    )
    overlays = load_overlay_files(overlay_paths)
    export_timeout = (
        export_timeout_override
        if export_timeout_override is not None
        else import_timeout_from_context(ctx)
    )

    preview = fetch_export_preview(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
        target=target_key,
        options=options or None,
    )
    # The preview describes the version without overlays; acknowledging it would make an
    # overlaid job fail STALE_PREVIEW, so only an overlay-free job is pinned to it.
    acknowledged_snapshot = None if overlays else projection_snapshot_hash(preview)

    accepted = start_export_job(
        client,
        tenant_slug,
        artifact=str(project_id),
        version=version,
        target=target_key,
        options=options or None,
        confirm=confirm,
        acknowledged_snapshot=acknowledged_snapshot,
        overlays=overlays,
    )
    job_id = accepted.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        typer.echo("Export job acceptance response missing job_id.", err=True)
        raise typer.Exit(EXIT_ERROR)

    status = wait_for_export_job(
        client,
        tenant_slug,
        job_id,
        poll_interval=poll_interval,
        timeout=export_timeout,
        no_progress=no_progress_from_context(ctx),
    )
    result = status.get("result")
    if not isinstance(result, dict):
        typer.echo("Completed export job missing result payload.", err=True)
        raise typer.Exit(EXIT_ERROR)

    fidelity = preview_fidelity({"fidelity": result.get("fidelity")})
    download_path = result.get("download_path")
    if not isinstance(download_path, str) or not download_path:
        typer.echo("Completed export job missing download_path.", err=True)
        raise typer.Exit(EXIT_ERROR)

    body, content_type, disposition = download_export_job_artifact(
        client,
        download_path=download_path,
        tenant_slug=tenant_slug,
        job_id=job_id,
    )
    files = result.get("files")
    file_rows = files if isinstance(files, list) else None
    disposition_name = filename_from_disposition(disposition)

    bytes_written, effective_out = write_export_artifact(
        body,
        out=out,
        content_type=content_type,
        files=file_rows,
        disposition_filename=disposition_name,
    )

    json_mode = json_mode_from_context(ctx)
    result_snapshot = result.get("snapshot_hash")
    metadata = SpecExportMetadata(
        output=effective_out,
        bytes_written=bytes_written,
        content_type=content_type,
        format=target_format,
        fidelity_target=target_key,
        fidelity=_fidelity_metadata(fidelity if isinstance(fidelity, dict) else None),
        filename=disposition_name,
        snapshot_hash=result_snapshot if isinstance(result_snapshot, str) else None,
    )
    emit_download_metadata(metadata, json_mode=json_mode)

    if not json_mode:
        for line in format_export_fidelity_summary(fidelity, target=target_key):
            typer.echo(line, err=True)
        for line in format_overlay_summary(result.get("overlay")):
            typer.echo(line, err=True)

    enforce_export_fidelity_gate(
        fidelity if isinstance(fidelity, dict) else None,
        force=force,
    )
