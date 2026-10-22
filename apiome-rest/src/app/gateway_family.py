"""The gateway family: one declaration per front end — FMT-7.6 (#5460).

Every gateway-configuration source (Kong, Gateway API, Envoy xDS, Istio, Traefik, nginx,
HAProxy, Consul, Tyk) produces the same flavor-neutral
:class:`~app.gateway_config_model.GatewayConfigDocument`. What still differs between them
is a handful of facts about the *source*, and before FMT-7.6 each fact was spelled in a
different module: the provenance split in the normalizer, the ledger label in the preview
manifest, the routing keys in :mod:`app.import_routing`, one normalizer class per flavor.

This module holds those facts once, as a :class:`GatewayFlavor` per front end, and is the
only place provenance is classified (:func:`provenance_stamp`). Adding a front end is a
:class:`GatewayFlavor` plus a route-extraction function that returns a
``GatewayConfigDocument`` — :func:`app.gateway_config_normalizer.register_gateway_flavor`
derives the normalizer, and the ledger label, routing reason and provenance follow from
the declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

from . import inference_provenance

__all__ = [
    "DECLARED",
    "INFERRED",
    "GATEWAY_FAMILY",
    "GatewayFlavor",
    "add_flavor",
    "flavor_for",
    "flavor_keys",
    "gateway_config_formats",
    "inferred_route_flavors",
    "policy_plugin_flavors",
    "provenance_stamp",
]

#: Route provenance of a flavor that *declares* its API surface to a gateway (the shared
#: FMT-8.6 vocabulary, :mod:`app.inference_provenance`).
DECLARED = inference_provenance.DECLARED

#: Route provenance of a flavor whose surface is reconstructed from runtime plumbing.
INFERRED = inference_provenance.INFERRED


@dataclass(frozen=True)
class GatewayFlavor:
    """The facts about one gateway front end that the shared middle needs.

    Attributes:
        key: Flavor / canonical format key (``kong``, ``traefik`` …).
        label: How the coverage ledger names a document of this flavor.
        route_provenance: :data:`DECLARED` — routes, hosts and methods are declared facts and
            carry no stamp — or :data:`INFERRED` — every operation and service is stamped
            ``provenance: inferred``.
        policy_plugins: List the flavor's non-auth plugins on the gateway report as policy
            the canonical model does not represent (rate limits, rewrites, middleware).
        aliases: Further format keys that route like this flavor (``kong-declarative``).
        parser: Dotted name of the route-extraction function, for error messages.
    """

    key: str
    label: str
    route_provenance: str
    policy_plugins: bool
    aliases: Tuple[str, ...] = ()
    parser: str = ""


#: Every gateway front end, in the order they were added to Apiome.
GATEWAY_FAMILY: Dict[str, GatewayFlavor] = {
    flavor.key: flavor
    for flavor in (
        # IXH-7.8: gateways an API surface is *declared* to. Gateway API filters stay off the
        # policy list — IXH-7.8 reports them through the route extras only.
        GatewayFlavor(
            "kong",
            "Kong declarative config",
            DECLARED,
            True,
            ("kong-declarative",),
            "app.kong_parser.parse_kong_declarative",
        ),
        GatewayFlavor(
            "gateway-api",
            "Gateway API HTTPRoute manifests",
            DECLARED,
            False,
            ("httproute",),
            "app.gateway_api_parser.parse_gateway_api",
        ),
        # FMT-7.4: service-mesh route tables — evidence of an API, not a declaration of one.
        GatewayFlavor(
            "envoy-xds", "Envoy xDS route configuration", INFERRED, True, (), "app.envoy_xds_parser.parse_envoy_xds"
        ),
        GatewayFlavor("istio", "Istio VirtualService manifests", INFERRED, True, (), "app.istio_parser.parse_istio"),
        # FMT-7.5: "the reverse-proxy config is the only spec".
        GatewayFlavor(
            "traefik", "Traefik dynamic configuration", INFERRED, True, (), "app.traefik_parser.parse_traefik"
        ),
        GatewayFlavor("nginx", "nginx configuration", INFERRED, True, (), "app.nginx_parser.parse_nginx"),
        GatewayFlavor("haproxy", "HAProxy configuration", INFERRED, True, (), "app.haproxy_parser.parse_haproxy"),
        GatewayFlavor("consul", "Consul service definitions", INFERRED, True, (), "app.consul_parser.parse_consul"),
        GatewayFlavor("tyk", "Tyk API definition", INFERRED, True, (), "app.tyk_parser.parse_tyk_classic"),
    )
}


def add_flavor(flavor: GatewayFlavor) -> GatewayFlavor:
    """Add a front end to the family (used by ``register_gateway_flavor``).

    Args:
        flavor: The declaration.

    Returns:
        The declaration as registered.

    Raises:
        ValueError: When the key is taken by a different declaration, or the provenance is
            neither :data:`DECLARED` nor :data:`INFERRED`.
    """
    if flavor.route_provenance not in (DECLARED, INFERRED):
        raise ValueError(f"route_provenance must be {DECLARED!r} or {INFERRED!r}, not {flavor.route_provenance!r}")
    existing = GATEWAY_FAMILY.get(flavor.key)
    if existing is not None and existing != flavor:
        raise ValueError(f"gateway flavor {flavor.key!r} is already declared differently")
    GATEWAY_FAMILY[flavor.key] = flavor
    return flavor


def flavor_for(key: str) -> Optional[GatewayFlavor]:
    """The declaration for a flavor key or alias, or ``None`` for a non-gateway key."""
    if key in GATEWAY_FAMILY:
        return GATEWAY_FAMILY[key]
    return next((flavor for flavor in GATEWAY_FAMILY.values() if key in flavor.aliases), None)


def flavor_keys() -> Tuple[str, ...]:
    """Every declared flavor key."""
    return tuple(GATEWAY_FAMILY)


def gateway_config_formats() -> FrozenSet[str]:
    """Every format key (flavor keys and aliases) that routes as a gateway surface."""
    return frozenset(key for flavor in GATEWAY_FAMILY.values() for key in (flavor.key, *flavor.aliases))


def inferred_route_flavors() -> FrozenSet[str]:
    """Flavors whose operations and services are all stamped inferred."""
    return frozenset(flavor.key for flavor in GATEWAY_FAMILY.values() if flavor.route_provenance == INFERRED)


def policy_plugin_flavors() -> FrozenSet[str]:
    """Flavors whose non-auth plugins are listed on the report as unmodelled policy."""
    return frozenset(flavor.key for flavor in GATEWAY_FAMILY.values() if flavor.policy_plugins)


def provenance_stamp(flavor_key: str, *, derived: bool = False) -> Dict[str, str]:
    """The provenance extras for one fact a gateway import produces — the only classifier.

    Args:
        flavor_key: The document's flavor.
        derived: The fact was *recovered* rather than read (a path parameter inferred from a
            regex, an auth scheme inferred from a plugin, gateway policy read from an
            extension); such a fact is inferred in every flavor.

    Returns:
        ``{"provenance": "inferred"}`` for a derived fact or any fact of an inferred flavor;
        ``{}`` for a declared fact of a declared flavor (the ledger reads an unstamped
        entity as mapped / partially mapped).

    Raises:
        KeyError: For a key that is not a gateway flavor — a programming error.
    """
    flavor = flavor_for(flavor_key)
    if flavor is None:
        raise KeyError(f"{flavor_key!r} is not a gateway flavor")
    if derived or flavor.route_provenance == INFERRED:
        return inference_provenance.provenance_extras(INFERRED)
    return {}
