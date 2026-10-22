"""nginx configuration import source — FMT-7.5 (#5459).

The :class:`~app.import_source.ImportSource` adapter for nginx ``server`` / ``location``
configuration — one file, or a configuration tree whose ``include`` directives are followed
across the files of the import. :mod:`app.nginx_parser` reads a **documented subset** of
nginx (the read, carried and declared directive tables it exports are this adapter's
capability vocabulary); everything outside it is a declared parsing limit on the coverage
ledger, never a silent omission. There are no request/response schemas, so the import
lands in the catalog as non-publishable and every operation is labelled ``inferred``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .gateway_config_normalizer import NGINX_FORMAT_KEY
from .import_source import NO_MATCH, DetectionInput, DetectionResult
from .nginx_parser import (
    NGINX_CARRIED_DIRECTIVES,
    NGINX_DECLARED_DIRECTIVES,
    NGINX_READ_DIRECTIVES,
    is_nginx,
    parse_nginx,
    parse_nginx_fileset,
)
from .proxy_import_source import ProxyRouteImportSource
from .proxy_route_common import directive_capabilities

__all__ = ["NginxImportSource"]

#: Confidence for text with nginx block structure and routing directives.
_CONFIDENCE = 0.9


class NginxImportSource(ProxyRouteImportSource, register=True):
    """Adapter for nginx configuration (file / url / paste / fileset)."""

    key = NGINX_FORMAT_KEY
    label = "nginx configuration"
    description = (
        "Import nginx server and location blocks — one file or a configuration tree with its "
        "includes — through a documented subset of nginx: each location becomes an operation "
        "(exact, prefix or regex path), server_name the hosts, listen … ssl the scheme, and "
        "proxy_pass the upstream it names. if, map, geo, try_files, named locations and the "
        "other directives outside the subset are declared parsing limits. There are no "
        "request/response schemas, so the import lands in the catalog as non-publishable and "
        "every operation is labelled inferred."
    )
    icon = "route"
    formats = ("nginx",)
    file_extensions = (".conf",)
    capabilities = directive_capabilities(
        "nginx",
        read=[f"directive.{name}" for name in NGINX_READ_DIRECTIVES],
        carried=[f"directive.{name}" for name in NGINX_CARRIED_DIRECTIVES],
        declared=list(NGINX_DECLARED_DIRECTIVES),
    )

    def detect(self, payload: DetectionInput) -> DetectionResult:
        if payload.text is not None and is_nginx(payload.text):
            return DetectionResult(
                confidence=_CONFIDENCE,
                format=NGINX_FORMAT_KEY,
                reason="`server { … }` / `upstream { … }` blocks with listen / location / proxy_pass",
            )
        return NO_MATCH

    def _parse_text(self, raw: str, *, source_label: Optional[str]) -> Any:
        return parse_nginx(raw, source_label=source_label)

    def _parse_members(self, members: Mapping[str, str], *, root: Optional[str], source_label: Optional[str]) -> Any:
        return parse_nginx_fileset(members, root=root, source_label=source_label)
