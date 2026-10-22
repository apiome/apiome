"""Consul service-definition import source — FMT-7.5 (#5459).

The :class:`~app.import_source.ImportSource` adapter for Consul's registry: service
definitions and catalog exports, and the ``service-router`` / ``ingress-gateway`` (with
``service-resolver``, ``-splitter`` and ``-defaults``) configuration entries, in JSON or
HCL, one file or a set. Only a ``service-router`` carries real paths; a registered HTTP
service no router describes becomes one inferred catch-all operation (or one per
``urlprefix-`` convention tag). There are no request/response schemas, so the import lands
in the catalog as non-publishable and every operation is labelled ``inferred``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .consul_parser import (
    CONSUL_DECLARED_CONSTRUCTS,
    CONSUL_READ_CONSTRUCTS,
    is_consul,
    parse_consul,
    parse_consul_fileset,
)
from .gateway_config_normalizer import CONSUL_FORMAT_KEY
from .import_source import NO_MATCH, DetectionInput, DetectionResult
from .proxy_import_source import ProxyRouteImportSource
from .proxy_route_common import directive_capabilities

__all__ = ["ConsulImportSource"]

#: Confidence for a Consul definition, catalog export or configuration entry.
_CONFIDENCE = 0.88


class ConsulImportSource(ProxyRouteImportSource, register=True):
    """Adapter for Consul service definitions and configuration entries."""

    key = CONSUL_FORMAT_KEY
    label = "Consul service definitions"
    description = (
        "Import Consul's service registry — service definitions, catalog exports and the "
        "service-router, ingress-gateway, service-resolver, -splitter and -defaults "
        "configuration entries, in JSON or HCL. Router path, method, header and query matches "
        "become operations; a registered HTTP service with no router becomes one catch-all "
        "operation (or one per urlprefix- tag). There are no request/response schemas, so the "
        "import lands in the catalog as non-publishable and every operation is labelled "
        "inferred."
    )
    icon = "route"
    formats = ("consul",)
    file_extensions = (".json", ".hcl")
    capabilities = directive_capabilities("consul", read=CONSUL_READ_CONSTRUCTS, declared=CONSUL_DECLARED_CONSTRUCTS)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        if payload.text is not None and is_consul(payload.text):
            return DetectionResult(
                confidence=_CONFIDENCE,
                format=CONSUL_FORMAT_KEY,
                reason="Consul `service` / `services` definition, catalog export or `Kind` entry",
            )
        return NO_MATCH

    def _parse_text(self, raw: str, *, source_label: Optional[str]) -> Any:
        return parse_consul(raw, source_label=source_label)

    def _parse_members(self, members: Mapping[str, str], *, root: Optional[str], source_label: Optional[str]) -> Any:
        return parse_consul_fileset(members, root=root, source_label=source_label)
