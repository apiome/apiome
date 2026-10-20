"""Agent security schemes → canonical :class:`~app.canonical_model.AgentSecurityScheme` — MFI-18.4.

A2A reuses the OpenAPI security-scheme object (``{type, scheme, in, name, bearerFormat,
flows, openIdConnectUrl, description}``) under ``securitySchemes``. This module maps one such
mapping onto the first-class canonical scheme list the agent-descriptor paradigm carries, keeping
any key it does not model in the scheme's ``extras`` so nothing is lost.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .canonical_model import AgentSecurityScheme

__all__ = ["agent_security_schemes"]

#: Source key → canonical field, for the keys :class:`AgentSecurityScheme` models directly.
_FIELD_BY_KEY = {
    "scheme": "scheme",
    "in": "location",
    "name": "parameter_name",
    "bearerFormat": "bearer_format",
    "openIdConnectUrl": "openid_connect_url",
    "flows": "flows",
    "description": "description",
}


def agent_security_schemes(schemes: Mapping[str, Any]) -> List[AgentSecurityScheme]:
    """Map ``{scheme name: scheme object}`` onto canonical schemes, sorted by name.

    Args:
        schemes: The agent's ``securitySchemes`` mapping, verbatim. A non-object entry is
            kept as a scheme of type ``unknown`` so a lint rule can still report it.

    Returns:
        One :class:`AgentSecurityScheme` per entry; unmodelled keys ride in ``extras``.
    """
    out: List[AgentSecurityScheme] = []
    for name in sorted(schemes):
        body = schemes[name] if isinstance(schemes[name], Mapping) else {}
        fields: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        for key, value in body.items():
            if key == "type":
                continue
            target = _FIELD_BY_KEY.get(key)
            if target == "flows" and isinstance(value, Mapping):
                fields[target] = dict(value)
            elif target is not None and target != "flows" and isinstance(value, str):
                fields[target] = value
            else:
                extras[key] = value
        scheme_type = body.get("type")
        out.append(
            AgentSecurityScheme(
                name=str(name),
                type=scheme_type if isinstance(scheme_type, str) and scheme_type else "unknown",
                extras=extras,
                **fields,
            )
        )
    return out
