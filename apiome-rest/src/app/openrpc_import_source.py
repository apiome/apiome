"""OpenRPC import source — MFI-18.6, MFI-19.1 (#3979).

The :class:`~app.import_source.ImportSource` adapter that makes OpenRPC JSON-RPC
service descriptions importable into the catalog (store-raw, MFI-23.7). A running service
is read live through the reserved ``rpc.discover`` method (:meth:`OpenRpcImportSource.discover`,
:mod:`app.openrpc_discovery`).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Optional

from . import openrpc_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .openrpc_discovery import discover_openrpc_service
from .openrpc_parser import (
    OpenRpcDocument,
    OpenRpcParseError,
    is_openrpc,
    is_openrpc_document,
    parse_openrpc,
)

__all__ = ["OpenRpcImportSource"]


class OpenRpcImportSource(ImportSource, register=True):
    """Adapter for OpenRPC JSON-RPC service descriptions (file / url / paste / live ``rpc.discover``)."""

    key = "openrpc"
    label = "OpenRPC"
    description = "Import an OpenRPC JSON-RPC 2.0 service description with methods and schemas."
    icon = "workflow"
    paradigm = ApiParadigm.RPC
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.DISCOVERY, InputKind.FILESET)
    #: A live JSON-RPC service is read by calling its ``rpc.discover`` method (MFI-19.1,
    #: :meth:`discover`).
    supports_live_discovery = True
    formats = ("openrpc", "jsonrpc")
    file_extensions = (".openrpc.json", ".openrpc", ".json")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_openrpc(text):
            return DetectionResult(
                confidence=0.98,
                format="openrpc",
                reason="`openrpc` version marker",
            )

        document = payload.document
        if document is not None and is_openrpc_document(document):
            return DetectionResult(
                confidence=0.98,
                format="openrpc",
                reason="`openrpc` version marker",
            )

        filename = (payload.filename or "").lower()
        if filename.endswith(".openrpc.json") or filename.endswith(".openrpc"):
            return DetectionResult(confidence=0.75, format="openrpc", reason="`.openrpc` file extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> OpenRpcDocument:
        try:
            return parse_openrpc(raw, source_label=source_label)
        except OpenRpcParseError as exc:
            raise ImportSourceError(str(exc)) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> OpenRpcDocument:
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("OpenRPC fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def discover(
        self,
        url: str,
        *,
        auth_type: Optional[str] = None,
        auth_payload: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        client: Optional[Any] = None,
    ) -> OpenRpcDocument:
        """Read a live JSON-RPC service's OpenRPC document through ``rpc.discover`` (MFI-19.1).

        The live counterpart to :meth:`parse`: :func:`app.openrpc_discovery.discover_openrpc_service`
        calls ``rpc.discover`` on the endpoint over the SSRF-guarded client, and the document it
        returns is parsed exactly as an upload is.

        Args:
            url: The JSON-RPC endpoint.
            auth_type: Credential-vault auth type.
            auth_payload: The decrypted credential for ``auth_type``.
            headers: Extra request headers.
            client: An httpx client to inject (tests).

        Returns:
            The parsed document, with ``discovery_url`` set to the endpoint.

        Raises:
            ImportSourceError: When the service cannot be reached, does not implement
                ``rpc.discover``, or its document does not parse.
        """
        discovery = discover_openrpc_service(
            url, auth_type=auth_type, auth_payload=auth_payload, headers=headers, client=client
        )
        document = self.parse(discovery.document, source_label=discovery.endpoint_url)
        return replace(document, discovery_url=discovery.endpoint_url)

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, OpenRpcDocument):
            raise ImportSourceError(
                "OpenRPC source must be an OpenRpcDocument (see app.openrpc_parser.parse_openrpc)"
            )
        return self._normalize_via_registry("openrpc", native_ast, include_raw=include_raw)
