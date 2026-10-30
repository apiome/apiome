"""HL7 FHIR import source — MFI-22.2, extended for R4 / R5 / R6 by MFI-20.1.

The :class:`~app.import_source.ImportSource` adapter that makes FHIR JSON documents importable into
the catalog (store-raw, MFI-23.7): StructureDefinition profiles, a server's CapabilityStatement and
resource instances, in any FHIR release (the release is recorded on the model; see
:mod:`app.fhir_normalizer`).

**Live discovery (MFI-20.1).** A FHIR server describes itself at ``GET <base>/metadata``.
:meth:`FhirImportSource.discover` fetches that CapabilityStatement over the SSRF-guarded live-fetch
client (:mod:`app.live_fetch`) and parses it exactly as an upload; the catalog's live refresh
(:mod:`app.catalog_refresh`) uses it to re-check a FHIR item against its server. Crawling a server's
profiles too is the MFI-18.5 registry crawl (:mod:`app.fhir_metadata_crawl`).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from . import fhir_normalizer  # noqa: F401 — self-registers the normalizer
from .canonical_model import ApiParadigm, CanonicalApi
from .fhir_parser import FhirDocument, FhirParseError, is_fhir, parse_fhir
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["FhirImportSource", "MAX_METADATA_BYTES", "metadata_url"]

#: Largest CapabilityStatement read from ``/metadata`` (bytes).
MAX_METADATA_BYTES = 16 * 1024 * 1024

_FHIR_JSON = "application/fhir+json, application/json;q=0.9"


def metadata_url(base_url: str) -> str:
    """The ``/metadata`` URL of a FHIR server, given its base URL or the ``/metadata`` URL itself.

    Args:
        base_url: ``https://host/fhir``, ``https://host/fhir/`` or ``https://host/fhir/metadata``.

    Returns:
        ``https://host/fhir/metadata`` (any query string kept).

    Raises:
        ImportSourceError: When the URL is not http(s).
    """
    parts = urlsplit((base_url or "").strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ImportSourceError(f"FHIR discovery needs an http(s) server base URL, not {base_url!r}")
    path = parts.path.rstrip("/")
    if not path.endswith("/metadata") and path != "metadata":
        path = f"{path}/metadata"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


class FhirImportSource(ImportSource, register=True):
    """Adapter for HL7 FHIR R4 / R5 / R6 JSON (profiles, CapabilityStatements, resources)."""

    key = "fhir"
    label = "FHIR"
    description = (
        "Import an HL7 FHIR R4, R5 or R6 CapabilityStatement (a server's /metadata), "
        "StructureDefinition profile or resource instance."
    )
    icon = "heart-pulse"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    supports_live_discovery = True
    formats = ("fhir", "fhirr4", "structuredefinition")
    file_extensions = (".fhir.json", ".structuredefinition.json", ".json")
    #: Registry crawl (MFI-18.5, :mod:`app.fhir_metadata_crawl`).
    registry_crawl = "fhir-metadata"

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_fhir(text):
            if '"resourceType": "StructureDefinition"' in text or '"resourceType":"StructureDefinition"' in text:
                reason = "`resourceType: StructureDefinition`"
                confidence = 0.98
            elif "hl7.org/fhir" in text.lower():
                reason = "HL7 FHIR profile URL marker"
                confidence = 0.97
            else:
                reason = "FHIR `resourceType` marker"
                confidence = 0.95
            return DetectionResult(confidence=confidence, format="fhir", reason=reason)

        filename = (payload.filename or "").lower()
        if filename.endswith(".fhir.json") or filename.endswith(".structuredefinition.json"):
            if text is not None and is_fhir(text):
                return DetectionResult(confidence=0.85, format="fhir", reason="FHIR filename extension")
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> FhirDocument:
        try:
            return parse_fhir(raw, source_label=source_label)
        except FhirParseError as exc:
            raise ImportSourceError(str(exc)) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> FhirDocument:
        root = fileset.root
        if root not in fileset.members:
            raise ImportSourceError("FHIR fileset is missing its root document")
        return self.parse(fileset.members[root], source_label=root or source_label)

    def discover(
        self,
        base_url: str,
        *,
        auth_type: Optional[str] = None,
        auth_payload: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        client: Optional[Any] = None,
    ) -> FhirDocument:
        """Read a live FHIR server's CapabilityStatement from ``<base>/metadata`` (MFI-20.1).

        Args:
            base_url: The server's base URL (or its ``/metadata`` URL).
            auth_type: Credential-vault auth type (``bearer``, ``header`` …), if the server needs one.
            auth_payload: The decrypted credential for ``auth_type``.
            timeout: Per-request timeout in seconds; the live-fetch default when omitted.
            client: An httpx client to inject (tests); an SSRF-guarded one otherwise.

        Returns:
            The parsed CapabilityStatement (``kind == "capability_statement"``), with the fetched
            JSON as ``raw``.

        Raises:
            ImportSourceError: When the URL is not allowed, the server cannot be reached or answers
                with an error, or the body is not a FHIR CapabilityStatement.
        """
        from .live_fetch import auth_headers, check_public_url, guarded_client, guarded_get

        url = metadata_url(base_url)
        check_public_url(url, what="FHIR server")
        headers = auth_headers(auth_type, auth_payload)
        owned = client is None
        if owned:
            if timeout is not None:
                import httpx

                from .ssrf_guard import build_guarded_client

                client = build_guarded_client(timeout=httpx.Timeout(float(timeout)), follow_redirects=True)
            else:
                client = guarded_client()
        try:
            text = guarded_get(
                client, url, accept=_FHIR_JSON, headers=headers, what="FHIR CapabilityStatement",
                max_bytes=MAX_METADATA_BYTES,
            )
        finally:
            if owned:
                client.close()
        document = self.parse(text, source_label=url)
        if document.kind != "capability_statement":
            raise ImportSourceError(f"{url} did not return a FHIR CapabilityStatement.")
        return document

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, FhirDocument):
            raise ImportSourceError(
                "FHIR source must be a FhirDocument (see app.fhir_parser.parse_fhir)"
            )
        return self._normalize_via_registry("fhir", native_ast, include_raw=include_raw)
