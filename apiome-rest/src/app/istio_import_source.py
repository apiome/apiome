"""Istio traffic-resource import source — FMT-7.4 (#5458).

The :class:`~app.import_source.ImportSource` adapter that makes Istio ``VirtualService``
routing importable — a single manifest, a multi-document stream (``Gateway`` +
``VirtualService`` + ``DestinationRule``), or a GitOps directory of them. ``http`` rules
become canonical operations; ``DestinationRule`` subsets are checked; ``Gateway`` servers
decide the scheme. There are no request/response schemas, so the import lands in the
catalog as a partial-fidelity, non-publishable item whose every operation is labelled
``inferred``.

Detection keys on ``apiVersion: networking.istio.io/*`` with an Istio networking kind,
which cannot collide with the Gateway API adapter's ``gateway.networking.k8s.io`` group.
A stream with a ``VirtualService`` is claimed with high confidence; one carrying only
supporting kinds (a lone ``DestinationRule``) is still Istio, but has no routes to import.
"""

from __future__ import annotations

from typing import Any, Optional

from . import gateway_config_normalizer  # noqa: F401 — self-registers the normalizers
from .canonical_model import ApiParadigm, CanonicalApi
from .fileset import IntakeFileset
from .gateway_config_model import GatewayConfigDocument, GatewayConfigParseError
from .gateway_config_normalizer import ISTIO_FORMAT_KEY
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .istio_parser import is_istio, is_istio_document, parse_istio, parse_istio_fileset

__all__ = ["IstioImportSource"]

#: Confidence when the stream carries a VirtualService.
_ROUTE_CONFIDENCE = 0.97

#: Confidence when the stream carries only supporting Istio kinds.
_SUPPORTING_CONFIDENCE = 0.8


class IstioImportSource(ImportSource, register=True):
    """Adapter for Istio VirtualService manifests (file / url / paste / fileset)."""

    key = ISTIO_FORMAT_KEY
    label = "Istio VirtualService"
    description = (
        "Import Istio traffic resources — VirtualService http rules, with the Gateway and "
        "DestinationRule resources they name, as one manifest, a multi-document stream or "
        "a GitOps directory — and infer canonical operations from each rule's uri, method, "
        "header and query matches, destinations, subsets and traffic policy. There are no "
        "request/response schemas, so the import lands in the catalog as non-publishable "
        "and every operation is labelled inferred; supply schemas and convert to promote."
    )
    icon = "route"
    paradigm = ApiParadigm.REST
    input_kinds = (
        InputKind.FILE,
        InputKind.URL,
        InputKind.PASTE,
        InputKind.FILESET,
    )
    supports_live_discovery = False
    formats = ("istio", "virtualservice")
    file_extensions = (".yaml", ".yml")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None:
            kind = is_istio(text)
            if kind is not None:
                return self._result(kind)
        document = payload.document
        if document is not None and is_istio_document(document):
            return self._result(str(document.get("kind")))
        return NO_MATCH

    @staticmethod
    def _result(kind: str) -> DetectionResult:
        """The detection result for the strongest Istio kind found."""
        if kind == "VirtualService":
            return DetectionResult(
                confidence=_ROUTE_CONFIDENCE,
                format=ISTIO_FORMAT_KEY,
                reason="`apiVersion: networking.istio.io/*` + `kind: VirtualService`",
            )
        return DetectionResult(
            confidence=_SUPPORTING_CONFIDENCE,
            format=ISTIO_FORMAT_KEY,
            reason=f"`apiVersion: networking.istio.io/*` + `kind: {kind}`",
        )

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
        try:
            return parse_istio(raw, source_label=source_label)
        except GatewayConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> GatewayConfigDocument:
        if not fileset.members:
            raise ImportSourceError("Istio fileset has no members", code="INPUT_MALFORMED")
        try:
            return parse_istio_fileset(
                fileset.members,
                root=fileset.root,
                source_label=source_label or fileset.root,
            )
        except GatewayConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, GatewayConfigDocument):
            raise ImportSourceError(
                "Istio source must be a GatewayConfigDocument (see app.istio_parser.parse_istio)"
            )
        return self._normalize_via_registry(ISTIO_FORMAT_KEY, native_ast, include_raw=include_raw)
