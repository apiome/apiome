"""Gateway configs as entities — pure rules and wire shapes — CDG-5.3 (#5981).

A **gateway config** is one (connector, environment): the APIs that environment serves, its auth and
rate-limit posture, and what a gateway configuration cannot carry. Connector sync keeps one row per
environment (:mod:`app.gateway_config_store`); this module holds what needs no database.

**Posture** is read from the served APIs' canonical models, which the import sources fill two ways
until FMT-7.6 (#5460) gives every gateway one shared shape:

* Kong (CDG-1.2, parsed into a :class:`~app.gateway_config_model.GatewayConfigDocument`) —
  ``extras["gateway"]``: ``auth`` hints, ``unmodeled_plugins`` (rate limits, transforms, CORS) and
  ``global_plugins``, plus ``credential_redactions``;
* AWS API Gateway, Azure APIM, Apigee (FMT-7.1–7.3) — ``extras["security"]`` (authorizers,
  ``validate-jwt``, ``VerifyAPIKey`` …) and ``extras["rate_limits"]`` (``rate-limit``, ``quota``,
  ``SpikeArrest`` …), on operations and on the model.

Only names and schemes are kept — never a credential (they are redacted when the configuration is
parsed, and this module copies no ``config`` values).

**Push-back** exports a governed catalog item back to the gateway's format. Emitters exist for Kong
(FMT-2.2) and Gateway API (FMT-2.3); AWS API Gateway, Azure APIM and Apigee emit modes are FMT-7.7
(#5461), still to come, so their gateway configs say so instead of offering a target.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .entity_owners import EntityOwnerRef

__all__ = [
    "GATEWAY_DECLARED_LOSSES",
    "GatewayConfigOut",
    "empty_posture",
    "gateway_config_slug",
    "merge_postures",
    "posture_from_api",
    "push_back",
]

#: What every gateway configuration cannot carry (the wording the import manifest uses too).
GATEWAY_DECLARED_LOSSES: Tuple[Dict[str, str], ...] = (
    {
        "construct": "request-response-schemas",
        "reason": "Gateway configs carry no request/response schemas — they say where a request "
        "goes, not what it carries. Its APIs are operations only.",
    },
)

#: A plugin or policy whose name says it limits traffic.
_RATE_LIMIT_NAME = re.compile(r"rate|quota|spike|throttl|limit", re.IGNORECASE)

#: Connector kind → the export target that writes the gateway's own format.
_PUSH_BACK_TARGETS = {"kong-konnect": "kong", "kong-admin": "kong"}

#: Connector kinds whose emit mode is FMT-7.7 (#5461).
_FMT_7_7_KINDS = frozenset({"aws-apigateway", "azure-apim", "apigee"})


def empty_posture() -> Dict[str, Any]:
    """A posture with nothing in it."""
    return {"auth": [], "rate_limits": [], "policies": [], "credential_redactions": 0}


def _auth_entry(record: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """``{scheme, via}`` from a security record or a Kong auth hint, or ``None`` without a scheme."""
    scheme = record.get("scheme") or record.get("type")
    if not scheme:
        return None
    via = record.get("plugin") or record.get("policy") or record.get("name") or ""
    return {"scheme": str(scheme), "via": str(via)}


def _limit_entry(record: Mapping[str, Any]) -> Dict[str, str]:
    """``{name, kind}`` from a rate-limit record."""
    name = record.get("policy") or record.get("name") or record.get("kind") or "rate limit"
    return {"name": str(name), "kind": str(record.get("kind") or record.get("policyType") or name)}


def _records(value: Any) -> Iterable[Mapping[str, Any]]:
    """The mapping entries of a list (anything else yields nothing)."""
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, Mapping)]
    return []


def posture_from_api(api: Any) -> Dict[str, Any]:
    """Fold one served API's canonical model into a gateway posture.

    Args:
        api: A :class:`~app.canonical_model.CanonicalApi` (anything with ``extras`` and ``services``
            whose operations have ``extras``).

    Returns:
        ``{auth: [{scheme, via}], rate_limits: [{name, kind}], policies: [name],
        credential_redactions: n}``.
    """
    posture = empty_posture()
    extras = getattr(api, "extras", None) or {}
    gateway = extras.get("gateway") if isinstance(extras, Mapping) else None
    if isinstance(gateway, Mapping):
        for hint in _records(gateway.get("auth")):
            entry = _auth_entry(hint)
            if entry:
                posture["auth"].append(entry)
        plugin_names = [str(p.get("name")) for p in _records(gateway.get("unmodeled_plugins")) if p.get("name")]
        plugin_names += [str(name) for name in gateway.get("global_plugins") or [] if isinstance(name, str)]
        for name in plugin_names:
            if _RATE_LIMIT_NAME.search(name):
                posture["rate_limits"].append({"name": name, "kind": name})
            else:
                posture["policies"].append(name)
        posture["credential_redactions"] = int(gateway.get("credential_redactions") or 0)
    holders: List[Mapping[str, Any]] = [extras] if isinstance(extras, Mapping) else []
    for service in getattr(api, "services", None) or []:
        for operation in getattr(service, "operations", None) or []:
            op_extras = getattr(operation, "extras", None)
            if isinstance(op_extras, Mapping):
                holders.append(op_extras)
    for holder in holders:
        for record in _records(holder.get("security")):
            entry = _auth_entry(record)
            if entry:
                posture["auth"].append(entry)
        for record in _records(holder.get("rate_limits")):
            posture["rate_limits"].append(_limit_entry(record))
    return merge_postures([posture])


def merge_postures(postures: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Merge postures: distinct entries, sorted; redaction counts summed.

    Args:
        postures: Postures from :func:`posture_from_api` (or stored ones).

    Returns:
        One posture.
    """
    auth: Dict[Tuple[str, str], Dict[str, str]] = {}
    limits: Dict[Tuple[str, str], Dict[str, str]] = {}
    policies = set()
    redactions = 0
    for posture in postures:
        for entry in posture.get("auth") or []:
            auth[(entry["scheme"], entry.get("via", ""))] = {"scheme": entry["scheme"], "via": entry.get("via", "")}
        for entry in posture.get("rate_limits") or []:
            limits[(entry["name"], entry.get("kind", ""))] = {"name": entry["name"], "kind": entry.get("kind", "")}
        policies.update(posture.get("policies") or [])
        redactions += int(posture.get("credential_redactions") or 0)
    return {
        "auth": [auth[key] for key in sorted(auth)],
        "rate_limits": [limits[key] for key in sorted(limits)],
        "policies": sorted(policies),
        "credential_redactions": redactions,
    }


def gateway_config_slug(connector_name: str, environment: str, taken: Iterable[str] = ()) -> str:
    """A handle for a gateway config: ``<connector>-<environment>``, made unique against ``taken``.

    Args:
        connector_name: The connector's name.
        environment: The environment ('' for none).
        taken: Slugs live gateway configs of the tenant already use.

    Returns:
        A slug matching V298's shape check.
    """
    base = re.sub(r"[^a-z0-9]+", "-", f"{connector_name} {environment}".lower()).strip("-")[:110].strip("-")
    base = base or "gateway"
    used = set(taken)
    candidate, n = base, 2
    while candidate in used:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def gateway_config_name(connector_name: str, environment: str) -> str:
    """``"<connector> · <environment>"``, or the connector's name when there is no environment."""
    return f"{connector_name} · {environment}" if environment else connector_name


def push_back(connector_kind: str) -> Dict[str, Optional[str]]:
    """What pushing a catalog item back to this gateway can use.

    Args:
        connector_kind: The connector's kind.

    Returns:
        ``{target, reason}``: the export target key (``kong``) and ``None``, or ``None`` and why —
        ``fmt-7.7`` for AWS API Gateway, Azure APIM and Apigee, ``unsupported`` otherwise.
    """
    target = _PUSH_BACK_TARGETS.get(connector_kind)
    if target:
        return {"target": target, "reason": None}
    if connector_kind in _FMT_7_7_KINDS:
        return {"target": None, "reason": "fmt-7.7"}
    return {"target": None, "reason": "unsupported"}


# ---------------------------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------------------------


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GatewayConnectorRef(_CamelModel):
    """The connector a gateway config comes from."""

    id: str
    name: str
    kind: str


class GatewayAuth(_CamelModel):
    """An auth scheme and the plugin or policy that enforces it."""

    scheme: str
    via: str = ""


class GatewayRateLimit(_CamelModel):
    """A rate-limit or quota plugin or policy."""

    name: str
    kind: str = ""


class GatewayPosture(_CamelModel):
    """Auth and rate-limit posture, by name and scheme only — never a credential."""

    auth: List[GatewayAuth] = Field(default_factory=list)
    rate_limits: List[GatewayRateLimit] = Field(default_factory=list)
    policies: List[str] = Field(default_factory=list, description="Other gateway plugins (transforms, CORS, …).")
    credential_redactions: int = Field(default=0, description="Credentials redacted from the configuration.")


class GatewayLoss(_CamelModel):
    """Something a gateway configuration cannot carry."""

    construct: str
    reason: str


class GatewayPushBack(_CamelModel):
    """Whether a catalog item can be pushed back to this gateway's format."""

    target: Optional[str] = Field(default=None, description="The export target (`kong`), or `null`.")
    reason: Optional[str] = Field(
        default=None, description="Why not: `fmt-7.7` (emit mode still to come, #5461) or `unsupported`."
    )


class GatewayServedApi(_CamelModel):
    """One API the environment serves (a connector item)."""

    item_id: str
    name: str
    remote_id: Optional[str] = None
    status: str
    hosts: List[str] = Field(default_factory=list)
    base_path: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    publishable: Optional[bool] = Field(
        default=None, description="`true` for a Project (`api`), `false` for a catalog item."
    )
    last_seen_at: Optional[datetime] = None


class GatewayConfigOut(_CamelModel):
    """A gateway config."""

    id: str
    slug: str
    name: str
    connector: GatewayConnectorRef
    environment: str
    flavor: str
    api_count: int
    posture: GatewayPosture
    declared_losses: List[GatewayLoss] = Field(default_factory=list)
    push_back: GatewayPushBack
    owner: Optional[EntityOwnerRef] = None
    apis: List[GatewayServedApi] = Field(default_factory=list, description="On a single read only.")
    last_synced_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GatewayConfigList(_CamelModel):
    """The tenant's live gateway configs."""

    gateway_configs: List[GatewayConfigOut]
