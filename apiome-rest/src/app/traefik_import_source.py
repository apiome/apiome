"""Traefik dynamic-configuration import source — FMT-7.5 (#5459).

The :class:`~app.import_source.ImportSource` adapter that makes Traefik routing importable:
a file-provider dynamic configuration in YAML or TOML, a watched directory of them, or a
Kubernetes stream of ``IngressRoute`` / ``Middleware`` resources. Router rules become
canonical operations through :mod:`app.traefik_parser`; there are no request/response
schemas, so the import lands in the catalog as a partial-fidelity, non-publishable item
whose every operation is labelled ``inferred``.

Detection keys on ``http.routers`` (YAML/TOML) or a ``traefik.io`` / ``traefik.containo.us``
``IngressRoute``. A document carrying only services or middlewares (a member of a provider
directory) is still Traefik, but has no route of its own.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .gateway_config_normalizer import TRAEFIK_FORMAT_KEY
from .import_source import NO_MATCH, DetectionInput, DetectionResult
from .proxy_import_source import ProxyRouteImportSource
from .proxy_route_common import directive_capabilities
from .traefik_parser import (
    TRAEFIK_DECLARED_CONSTRUCTS,
    TRAEFIK_READ_CONSTRUCTS,
    is_traefik,
    parse_traefik,
    parse_traefik_fileset,
)

__all__ = ["TraefikImportSource"]

#: Confidence when the text declares HTTP routers or an IngressRoute.
_ROUTER_CONFIDENCE = 0.93

#: Confidence when the text is Traefik but carries no router (services / middlewares only).
_SUPPORTING_CONFIDENCE = 0.6


class TraefikImportSource(ProxyRouteImportSource, register=True):
    """Adapter for Traefik dynamic configuration (file / url / paste / fileset)."""

    key = TRAEFIK_FORMAT_KEY
    label = "Traefik dynamic config"
    description = (
        "Import Traefik routing — the file provider's dynamic configuration (YAML or TOML, "
        "one file or a watched directory) or IngressRoute and Middleware resources — and "
        "infer canonical operations from each router's rule: Path / PathPrefix / PathRegexp, "
        "Host, Method, Header and Query matchers, with the boolean composition expanded. "
        "Middlewares ride on the operations as policy. There are no request/response schemas, "
        "so the import lands in the catalog as non-publishable and every operation is labelled "
        "inferred; supply schemas and convert to promote."
    )
    icon = "route"
    formats = ("traefik",)
    file_extensions = (".yml", ".yaml", ".toml")
    capabilities = directive_capabilities("traefik", read=TRAEFIK_READ_CONSTRUCTS, declared=TRAEFIK_DECLARED_CONSTRUCTS)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        verdict = is_traefik(payload.text) if payload.text is not None else None
        if verdict == "routers":
            return DetectionResult(
                confidence=_ROUTER_CONFIDENCE,
                format=TRAEFIK_FORMAT_KEY,
                reason="`http.routers` (Traefik dynamic configuration) or `kind: IngressRoute`",
            )
        if verdict == "supporting":
            return DetectionResult(
                confidence=_SUPPORTING_CONFIDENCE,
                format=TRAEFIK_FORMAT_KEY,
                reason="Traefik services / middlewares with no router",
            )
        return NO_MATCH

    def _parse_text(self, raw: str, *, source_label: Optional[str]) -> Any:
        return parse_traefik(raw, source_label=source_label)

    def _parse_members(self, members: Mapping[str, str], *, root: Optional[str], source_label: Optional[str]) -> Any:
        return parse_traefik_fileset(members, root=root, source_label=source_label)
