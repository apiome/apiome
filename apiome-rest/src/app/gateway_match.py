"""The one match-normalization table of the gateway family — FMT-7.6 (#5460).

Nine gateway front ends (Kong, Gateway API, Envoy xDS, Istio, Traefik, nginx, HAProxy,
Consul, Tyk) each spell a path match and a header/query match their own way. Before
FMT-7.6 the mapping from those spellings to the flavor-neutral
:class:`~app.gateway_config_model.GatewayPathPattern` lived in several places — a table
in the Gateway API parser, literal kind strings in the Kong parser, operator tables
re-spelled in the HAProxy and Consul parsers — and they had already drifted (an empty
prefix value rendered as ``prefix:`` in one front end and as ``""`` in another).

This module is the single implementation. A front end translates its own vocabulary
into one of two shared vocabularies and calls one function:

* **Path matches** use the Gateway API path types, ``Exact`` / ``PathPrefix`` /
  ``RegularExpression`` (:data:`PATH_TYPE_KINDS`), through :func:`path_pattern`.
* **Value matches** (headers, query parameters, methods written as matchers) use the
  operators in :data:`STRING_MATCH_OPERATORS`, through :func:`render_match_value`.

``tests/test_gateway_family.py`` proves there is exactly one table: every front end's
own matcher table maps onto these keys, and no front-end module builds a pattern or
renders an operator any other way.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .gateway_config_model import GatewayPathPattern, build_path_pattern

__all__ = [
    "PATH_KIND_TYPES",
    "PATH_TYPE_KINDS",
    "STRING_MATCH_OPERATORS",
    "parse_match_value",
    "path_pattern",
    "render_match_value",
    "template_params",
]

#: Gateway API ``path.type`` → flavor-neutral pattern kind. The only path-match table in the
#: family; :mod:`app.gateway_api_emitter` spells it in reverse through :data:`PATH_KIND_TYPES`.
PATH_TYPE_KINDS: Dict[str, str] = {
    "Exact": "exact",
    "PathPrefix": "prefix",
    "RegularExpression": "regex",
}

#: Flavor-neutral pattern kind → Gateway API ``path.type`` — derived, never written twice.
PATH_KIND_TYPES: Dict[str, str] = {kind: path_type for path_type, kind in PATH_TYPE_KINDS.items()}

#: Value-match operator → the prefix it renders with in a ``match_value`` (``""`` for exact,
#: which renders as the bare value a request must carry).
STRING_MATCH_OPERATORS: Dict[str, str] = {
    "exact": "",
    "prefix": "prefix",
    "suffix": "suffix",
    "contains": "contains",
    "regex": "regex",
}


#: ``{name}`` path-template parameter.
_TEMPLATE_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}")


def template_params(path: str) -> Tuple[str, ...]:
    """The ``{name}`` parameters of a path template, in order, each once."""
    names: List[str] = []
    for name in _TEMPLATE_PARAM_RE.findall(path):
        if name not in names:
            names.append(name)
    return tuple(names)


def path_pattern(path_type: str, value: str, *, templated: bool = False) -> GatewayPathPattern:
    """Normalize one path match — the only way a front end builds a path pattern.

    Args:
        path_type: ``Exact``, ``PathPrefix`` or ``RegularExpression`` — the Gateway API
            spelling every front end's own matcher table maps onto.
        value: The path or regex as the source declared it.
        templated: The format writes ``{name}`` path templates (Tyk, Traefik v2, Consul
            convention tags): an exact / prefix pattern then keeps each name as an inferred
            path parameter. Formats whose braces are literal leave this ``False``.

    Returns:
        The flavor-neutral pattern.

    Raises:
        KeyError: When ``path_type`` is not a Gateway API path type — a programming error in
            a front end's matcher table, never a property of input.
    """
    kind = PATH_TYPE_KINDS[path_type]
    if templated and kind != "regex":
        path = value.strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        return GatewayPathPattern(raw=value, kind=kind, template=path, param_names=template_params(path))
    return build_path_pattern(value, kind)


def render_match_value(operator: str, value: str) -> str:
    """Render one value match for a parameter's ``match_value`` extra.

    An exact match renders as the bare value; any other operator as ``<operator>:<value>``,
    so a reader can tell a prefix from a literal. An empty value is a presence-only match
    whatever the operator, and renders as ``""``.

    Args:
        operator: A key of :data:`STRING_MATCH_OPERATORS`.
        value: The value as declared.

    Returns:
        The rendered value.

    Raises:
        KeyError: For an operator outside the shared vocabulary (a front-end bug).
    """
    prefix = STRING_MATCH_OPERATORS[operator]
    return f"{prefix}:{value}" if prefix and value else value


def parse_match_value(rendered: str) -> Tuple[str, str]:
    """Split a rendered ``match_value`` back into ``(operator, value)`` — FMT-7.7.

    The exact inverse of :func:`render_match_value`, so an emitter can write a value match
    in its own product's syntax: ``prefix:acme-`` → ``("prefix", "acme-")``, ``GET`` →
    ``("exact", "GET")``, ``""`` → ``("exact", "")`` (presence only).

    Args:
        rendered: The ``match_value`` as the normalizer wrote it.

    Returns:
        The operator (a key of :data:`STRING_MATCH_OPERATORS`) and the value.
    """
    for operator, prefix in STRING_MATCH_OPERATORS.items():
        if prefix and rendered.startswith(prefix + ":"):
            return operator, rendered[len(prefix) + 1 :]
    return "exact", rendered
