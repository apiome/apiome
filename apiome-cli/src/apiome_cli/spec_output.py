"""Write spec export artifacts and emit response metadata on the correct streams."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import typer

from apiome_cli.client.spec_download import (
    SpecDownloadResult,
    SpecSerialization,
)
from apiome_cli.exit_codes import EXIT_ERROR


@dataclass(frozen=True)
class SpecExportMetadata:
    """Structured metadata for spec export and original-artifact download."""

    output: str
    bytes_written: int
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    # A reconstructed spec format (``openapi``/``arazzo``) or an emitter target key (``asyncapi``).
    format: str | None = None
    serialization: SpecSerialization | None = None
    source_openapi_version: str | None = None
    fidelity_target: str | None = None
    fidelity: dict[str, object] | None = None
    filename: str | None = None
    snapshot_hash: str | None = None


def write_document_bytes(body: bytes, output: str) -> None:
    """Write document bytes to a file path or stdout.

    Parameters
    ----------
    body:
        Raw document or artifact bytes.
    output:
        Destination file path, or ``-`` for stdout.

    Raises
    ------
    typer.Exit
        ``EXIT_ERROR`` when the destination file cannot be written.
    """
    if output == "-":
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()
        return
    try:
        Path(output).write_bytes(body)
    except OSError as exc:
        typer.echo(f"Failed to write {output!r}: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc


def metadata_stream(*, json_mode: bool, output: str) -> bool:
    """Return True when metadata should be written to stderr instead of stdout.

    Human-readable metadata always uses stderr (diagnostics). Global ``--json``
    metadata uses stdout when the document is written to a file, and stderr when
    ``--output -`` keeps stdout byte-safe for pipelines.
    """
    if not json_mode:
        return True
    return output == "-"


def emit_metadata_human(metadata: SpecExportMetadata, *, to_stderr: bool) -> None:
    """Print human-readable export metadata."""
    lines = [
        f"Wrote {metadata.bytes_written} bytes to {metadata.output}",
    ]
    if metadata.format is not None:
        lines.append(f"Format: {metadata.format}")
    if metadata.serialization is not None:
        lines.append(f"Serialization: {metadata.serialization}")
    if metadata.content_type:
        lines.append(f"Content-Type: {metadata.content_type}")
    if metadata.etag:
        lines.append(f"ETag: {metadata.etag}")
    if metadata.checksum:
        lines.append(f"Checksum: {metadata.checksum}")
    if metadata.filename:
        lines.append(f"Filename: {metadata.filename}")
    if metadata.source_openapi_version:
        lines.append(f"Source OpenAPI version: {metadata.source_openapi_version}")
    if metadata.fidelity_target:
        lines.append(f"Fidelity target: {metadata.fidelity_target}")
    if metadata.fidelity is not None:
        status = metadata.fidelity.get("status")
        if isinstance(status, str):
            lines.append(f"Fidelity: {status}")
    message = "\n".join(lines)
    if to_stderr:
        typer.echo(message, err=True)
    else:
        typer.echo(message)


def emit_metadata_json(metadata: SpecExportMetadata, *, to_stderr: bool) -> None:
    """Print compact JSON metadata for machine-readable invocations."""
    payload: dict[str, Any] = asdict(metadata)
    payload = {key: value for key, value in payload.items() if value is not None}
    message = json.dumps(payload, separators=(",", ":"))
    if to_stderr:
        typer.echo(message, err=True)
    else:
        typer.echo(message)


def emit_download_metadata(
    metadata: SpecExportMetadata,
    *,
    json_mode: bool,
) -> None:
    """Emit metadata on the stream chosen by ``metadata_stream``."""
    to_stderr = metadata_stream(json_mode=json_mode, output=metadata.output)
    if json_mode:
        emit_metadata_json(metadata, to_stderr=to_stderr)
    else:
        emit_metadata_human(metadata, to_stderr=to_stderr)


def build_spec_export_metadata(
    *,
    download: SpecDownloadResult,
    scope_source_openapi_version: str | None,
    scope_fidelity_target: str | None,
    fidelity: dict[str, object] | None,
    output: str,
) -> SpecExportMetadata:
    """Build metadata for a reconstructed spec export."""
    return SpecExportMetadata(
        output=output,
        bytes_written=len(download.body),
        content_type=download.content_type,
        etag=download.etag,
        format=download.format,
        serialization=download.serialization,
        source_openapi_version=scope_source_openapi_version,
        fidelity_target=scope_fidelity_target,
        fidelity=fidelity,
    )
