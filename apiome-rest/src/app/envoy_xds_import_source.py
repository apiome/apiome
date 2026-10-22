"""Envoy xDS route-configuration import source — FMT-7.4 (#5458).

The :class:`~app.import_source.ImportSource` adapter that makes Envoy's routing truth
importable: a static bootstrap, a bare ``RouteConfiguration``, an xDS
``DiscoveryResponse``, or a filesystem-xDS set (bootstrap plus the ``rds``/``cds`` files it
loads). Route tables carry no request/response schemas, so the import lands in the
catalog as a partial-fidelity, non-publishable item whose every operation is labelled
``inferred``; the missing schemas are stated on the coverage ledger as a capability limit
of the format, never as a drop.

Detection keys on Envoy-only structure — ``static_resources`` / ``dynamic_resources``, a
``virtual_hosts[]`` route configuration, or an ``envoy.config.*`` type URL — none of
which the sibling ``istio`` (``networking.istio.io``) or ``gateway-api``
(``gateway.networking.k8s.io``) markers can produce.
"""

from __future__ import annotations

from typing import Any, Optional

from . import gateway_config_normalizer  # noqa: F401 — self-registers the normalizers
from .canonical_model import ApiParadigm, CanonicalApi
from .envoy_xds_parser import (
    classify_envoy_document,
    is_envoy_xds,
    parse_envoy_xds,
    parse_envoy_xds_fileset,
)
from .fileset import IntakeFileset
from .gateway_config_model import GatewayConfigDocument, GatewayConfigParseError
from .gateway_config_normalizer import ENVOY_XDS_FORMAT_KEY
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)

__all__ = ["EnvoyXdsImportSource"]

#: Detection confidence for unmistakable Envoy structure.
_CONFIDENCE = 0.95

#: Detection reason, shared by the text and pre-parsed paths.
_REASON = "Envoy bootstrap / `RouteConfiguration` (`virtual_hosts[]`) / `envoy.config.*` xDS resource"


class EnvoyXdsImportSource(ImportSource, register=True):
    """Adapter for Envoy xDS route configuration (file / url / paste / fileset)."""

    key = ENVOY_XDS_FORMAT_KEY
    label = "Envoy xDS routes"
    description = (
        "Import Envoy route configuration — a static bootstrap, a RouteConfiguration, an xDS "
        "DiscoveryResponse, or a filesystem-xDS set — and infer canonical operations from "
        "each virtual host's routes: prefix, exact, segment-prefix and regex path matchers, "
        "header and query-parameter matches, clusters and traffic policy. Route tables carry "
        "no request/response schemas, so the import lands in the catalog as non-publishable "
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
    formats = ("envoy-xds", "envoy")
    file_extensions = (".yaml", ".yml", ".json")

    def detect(self, payload: DetectionInput) -> DetectionResult:
        text = payload.text
        if text is not None and is_envoy_xds(text):
            return DetectionResult(confidence=_CONFIDENCE, format=ENVOY_XDS_FORMAT_KEY, reason=_REASON)
        document = payload.document
        if document is not None and classify_envoy_document(document) is not None:
            return DetectionResult(confidence=_CONFIDENCE, format=ENVOY_XDS_FORMAT_KEY, reason=_REASON)
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
        try:
            return parse_envoy_xds(raw, source_label=source_label)
        except GatewayConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def parse_fileset(
        self,
        fileset: IntakeFileset,
        *,
        source_label: Optional[str] = None,
    ) -> GatewayConfigDocument:
        if not fileset.members:
            raise ImportSourceError("Envoy xDS fileset has no members", code="INPUT_MALFORMED")
        try:
            return parse_envoy_xds_fileset(
                fileset.members,
                root=fileset.root,
                source_label=source_label or fileset.root,
            )
        except GatewayConfigParseError as exc:
            raise ImportSourceError(str(exc), code=exc.code) from exc

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(native_ast, GatewayConfigDocument):
            raise ImportSourceError(
                "Envoy xDS source must be a GatewayConfigDocument "
                "(see app.envoy_xds_parser.parse_envoy_xds)"
            )
        return self._normalize_via_registry(
            ENVOY_XDS_FORMAT_KEY, native_ast, include_raw=include_raw
        )
