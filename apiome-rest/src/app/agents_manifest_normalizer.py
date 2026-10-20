"""Agentic-web site manifest → canonical model normalizer — MFI-18.3 (#3976).

Maps a parsed :class:`~app.agents_manifest_parser.AgentsManifest` (agents.json, AWP agent.json,
agents.txt or llms.txt) onto a :class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.AGENT`, beside the A2A and ACP adapters.

The mapping
-----------
* **Each protocol** the site declares (``a2a``, ``mcp``, ``acp``, ``skills``, ``ucp``,
  ``webmcp``, ``openapi``, ``manifest``, ``docs``, ``x-…``) is one
  :class:`~app.canonical_model.Service` keyed by its protocol id. AWP actions that are not routed
  ``via`` a protocol go under an ``actions`` service.
* **Each endpoint** is one :class:`~app.canonical_model.Operation` keyed
  ``<protocol>.<url as written>``, so an endpoint added or removed between two crawls of the site
  is an added / removed ``operation`` entry, and a changed description or transport is a changed
  one. The URL as written and its resolved form, the title and protocol attributes sit on
  ``extras``.
* **Each AWP action** is an operation keyed ``<via or actions>.<id>``, its method and endpoint on
  ``http_method`` / ``extras``.
* **Payment layers** (x402, AP2, MPP …) are metadata only: they live in the model's
  ``extras.payments`` and never become services.
* **Discovery seeds** (:func:`app.agents_manifest_parser.discovery_seeds`) — the A2A cards, ACP
  servers, MCP servers and nested manifests the site points at — are listed in
  ``extras.discovery_seeds`` as ``{protocol, url, importer}`` so a crawler (MFI-18.5) or a person
  can follow them.
* The site URL, when known, is the model's :class:`~app.canonical_model.Server`.

A repeated endpoint (same protocol and URL) or action id is keyed ``~2`` … by
:func:`app.agent_paradigm_keys.unique_keys` and marked ``extras.duplicate_of``; the lint pack
reports it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .agent_paradigm_keys import unique_keys
from .agents_manifest_parser import (
    AgentsManifest,
    ManifestAction,
    ManifestEndpoint,
    discovery_seeds,
    dumps_manifest_for_raw,
)
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Server,
    Service,
    StreamingMode,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["ACTIONS_SERVICE", "FORMAT_KEY", "PROTOCOL_LABELS", "AgentsManifestNormalizer"]

#: The normalizer / adapter format key.
FORMAT_KEY = "agents-manifest"

#: Service key for AWP actions that are not routed through a declared protocol.
ACTIONS_SERVICE = "actions"

#: Display names of the protocol services; an unlisted (``x-``) id is shown as written.
PROTOCOL_LABELS: Dict[str, str] = {
    "a2a": "A2A agents",
    "acp": "ACP agents",
    "mcp": "MCP servers",
    "skills": "Agent skills",
    "ucp": "UCP profiles",
    "webmcp": "WebMCP pages",
    "openapi": "OpenAPI documents",
    "graphql": "GraphQL endpoints",
    "manifest": "Site manifests",
    "docs": "Documentation",
    ACTIONS_SERVICE: "Actions",
}


class AgentsManifestNormalizer(Normalizer, register=True):
    """Normalize a parsed site manifest into a :class:`CanonicalApi`."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.AGENT

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map the manifest onto the canonical agent paradigm.

        Args:
            source: The parsed manifest (:class:`AgentsManifest`).
            include_raw: Whether to keep the document verbatim in ``raw``.

        Returns:
            The order-normalized canonical model.

        Raises:
            ValueError: When ``source`` is not a parsed site manifest.
        """
        if not isinstance(source, AgentsManifest):
            raise ValueError(
                "Site manifest source must be an AgentsManifest "
                "(see app.agents_manifest_parser.parse_agents_manifest)"
            )

        operations: Dict[str, List[Operation]] = {}
        endpoint_keys = unique_keys(
            [Keys.operation_rpc(e.protocol, e.url or "(empty)") for e in source.endpoints]
        )
        for endpoint, (key, duplicate_of) in zip(source.endpoints, endpoint_keys):
            operations.setdefault(endpoint.protocol, []).append(
                _endpoint_operation(endpoint, key, duplicate_of)
            )
        declared = {e.protocol for e in source.endpoints}
        action_keys = unique_keys(
            [Keys.operation_rpc(_action_service(a, declared), a.id) for a in source.actions]
        )
        for action, (key, duplicate_of) in zip(source.actions, action_keys):
            operations.setdefault(_action_service(action, declared), []).append(
                _action_operation(action, key, duplicate_of, declared)
            )

        seeds = discovery_seeds(source)
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol=source.dialect,
            identity=ApiIdentity(name=source.title),
            title=source.title,
            description=source.description,
            servers=[Server(url=source.site_url, name="Site", protocol="https")]
            if source.site_url
            else [],
            services=[
                Service(
                    key=protocol,
                    name=PROTOCOL_LABELS.get(protocol, protocol),
                    operations=ops,
                    extras={"protocol": protocol, "endpoint_count": len(ops)},
                )
                for protocol, ops in operations.items()
            ],
            raw={FORMAT_KEY: dumps_manifest_for_raw(source)} if include_raw else None,
            extras={
                "dialect": source.dialect,
                "spec_version": source.spec_version,
                "site_url": source.site_url,
                "protocols": sorted(operations),
                "endpoint_count": len(source.endpoints),
                "action_count": len(source.actions),
                "payments": [
                    {"protocol": p.protocol, **({"details": p.attributes} if p.attributes else {})}
                    for p in sorted(source.payments, key=lambda p: p.protocol)
                ],
                "authorization": list(source.authorization),
                "policies": dict(source.policies),
                # Sorted, like the services, so a reordered manifest fingerprints the same.
                "discovery_seeds": sorted(
                    (seed.as_dict() for seed in seeds), key=lambda d: (d["protocol"], d["url"])
                ),
            },
        )
        return normalize_ordering(api)


def _endpoint_operation(
    endpoint: ManifestEndpoint, key: str, duplicate_of: Optional[str]
) -> Operation:
    """Build the operation for one declared endpoint.

    Args:
        endpoint: The parsed endpoint.
        key: Its unique operation key.
        duplicate_of: The first occurrence's key when this endpoint repeats one.

    Returns:
        The operation; the URL as written, its resolved form and attributes on ``extras``.
    """
    extras: Dict[str, Any] = {
        "endpoint": True,
        "protocol": endpoint.protocol,
        "url": endpoint.url,
        "resolved_url": endpoint.resolved_url,
        "attributes": dict(endpoint.attributes),
    }
    if duplicate_of is not None:
        extras["duplicate_of"] = duplicate_of
    return Operation(
        key=key,
        name=endpoint.title or endpoint.url or "(empty)",
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        description=endpoint.description,
        extras=extras,
    )


def _action_service(action: ManifestAction, declared: set) -> str:
    """The service an AWP action belongs to: its ``via`` protocol when declared, else actions."""
    return action.via if action.via and action.via in declared else ACTIONS_SERVICE


def _action_operation(
    action: ManifestAction, key: str, duplicate_of: Optional[str], declared: set
) -> Operation:
    """Build the operation for one AWP action.

    Args:
        action: The parsed action.
        key: Its unique operation key.
        duplicate_of: The first occurrence's key when this action repeats an id.
        declared: The protocol ids the manifest declares (to flag an undeclared ``via``).

    Returns:
        The operation; method on ``http_method``, endpoint and routing on ``extras``.
    """
    extras: Dict[str, Any] = {
        "action": True,
        "url": action.endpoint,
        "resolved_url": action.resolved_endpoint,
        "via": action.via,
        "via_declared": action.via is None or action.via in declared,
        "operation": action.operation,
        "auth_required": action.auth_required,
        "inputs": dict(action.inputs),
    }
    if duplicate_of is not None:
        extras["duplicate_of"] = duplicate_of
    return Operation(
        key=key,
        name=action.id,
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        description=action.description,
        http_method=action.method,
        extras=extras,
    )
