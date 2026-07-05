"""Emit an export document through the emitter registry — MFX-11.5 (#3878).

Thin HTTP helper over ``POST /v1/export/{tenant}/document``, the emit counterpart to the dry-run
fidelity preview (:mod:`apiome_cli.client.export_registry`): ``/preview`` predicts the loss, this
route returns the bytes. It gives non-OpenAPI targets (AsyncAPI, GraphQL SDL, protobuf/gRPC) a document source the OpenAPI-only
browse reconstruction (:mod:`apiome_cli.client.spec_download`) cannot supply, so ``export asyncapi``,
``export grpc``, and ``export graphql`` can write the artifact while ``/preview`` supplies its honest fidelity report.

The server serializes the document as JSON (default) or YAML (``Accept: application/yaml``); this
helper only chooses the wire format and hands back the raw bytes + response metadata — all
presentation lives in the command and :mod:`apiome_cli.spec_output`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from apiome_cli.client import api_paths
from apiome_cli.client.errors import exit_on_api_error
from apiome_cli.client.http import RestClient
from apiome_cli.client.spec_download import SpecSerialization


@dataclass(frozen=True)
class ExportDocument:
    """An emitted export document's bytes and the response metadata a caller writes/reports."""

    body: bytes
    content_type: str | None
    filename: str | None
    serialization: SpecSerialization | None


def _filename_from_disposition(disposition: str | None) -> str | None:
    """Extract the ``filename="…"`` hint from a ``Content-Disposition`` header, if present."""
    if not disposition:
        return None
    marker = 'filename="'
    start = disposition.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = disposition.find('"', start)
    if end == -1:
        return None
    return disposition[start:end] or None


def fetch_export_document(
    client: RestClient,
    tenant_slug: str,
    *,
    artifact: str,
    version: str | None,
    target: str,
    serialization: SpecSerialization | None,
    options: Mapping[str, Any] | None = None,
) -> ExportDocument:
    """Emit ``target`` for one artifact revision and return the document bytes.

    Parameters
    ----------
    client:
        Authenticated REST client (API key + tenant scope).
    tenant_slug:
        The tenant URL slug.
    artifact:
        The artifact (project) id being exported.
    version:
        Revision UUID / version label, or ``None`` for the latest revision.
    target:
        Target emitter key (``asyncapi``) or format key (``asyncapi-3``).
    serialization:
        ``json`` or ``yaml`` — sets the ``Accept`` header the server negotiates on.
        Pass ``None`` to omit the ``Accept`` header (e.g. for binary targets such as
        ``protobuf`` that return ``text/x-protobuf`` or ``text/plain``).
    options:
        Optional per-target emit options (MFX-1.4); omitted applies the target defaults.

    Returns
    -------
    ExportDocument
        The emitted document bytes plus its content type, filename hint, and serialization.
    """
    body: dict[str, Any] = {"artifact": artifact, "target": target}
    if version is not None:
        body["version"] = version
    if options:
        body["options"] = dict(options)

    headers: dict[str, str] = {}
    if serialization == "yaml":
        headers["Accept"] = "application/yaml"
    elif serialization == "json":
        headers["Accept"] = "application/json"
    response = client.post_raw(
        api_paths.export_document(tenant_slug),
        json=body,
        headers=headers,
    )
    exit_on_api_error(response)
    return ExportDocument(
        body=response.content,
        content_type=response.headers.get("Content-Type"),
        filename=_filename_from_disposition(response.headers.get("Content-Disposition")),
        serialization=serialization,
    )
