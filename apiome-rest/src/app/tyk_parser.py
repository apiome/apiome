"""Parser for Tyk API definitions — FMT-7.5 (#5459).

Tyk writes an API in two forms, and they need different readers:

* **Classic** (``api_id`` + ``proxy.listen_path`` + ``version_data``) is a gateway
  routing surface with no schemas, read here into the flavor-neutral
  :class:`~app.gateway_config_model.GatewayConfigDocument`. Each version's
  ``extended_paths.white_list`` (and ``ignored``) entry is a route — the public path is
  ``listen_path`` + the entry's path, one operation per ``method_actions`` method, with
  ``{param}`` segments kept as inferred path parameters. A version with no white list
  proxies everything under the listen path, which is one catch-all route. Every other
  per-path rule (``cache``, ``hard_timeouts``, ``validate_json``, ``url_rewrites``,
  ``transform``, ``circuit_breakers`` …) rides as named policy on the route it names.
  The auth flags (``use_keyless``, ``use_oauth2``, ``enable_jwt`` …) become auth hints.
  A policies file supplied alongside contributes the quotas and rate limits of the
  policies granting access to the API, as consumer-scoped policy.
* **Tyk OAS** is an OpenAPI document carrying ``x-tyk-api-gateway``. It is a real spec,
  so it is read through the OpenAPI path (schemas included) and the extension is
  interpreted on top: :func:`interpret_tyk_oas` attaches the per-operation middleware
  (keyed by ``operationId``) and writes the same ``gateway`` report the classic form gets.

Declared, never silently dropped: ``validate_json`` schemas (carried as validation
policy, not modelled as message types), an inline GraphQL SDL (the proxy is imported;
the schema belongs to the GraphQL adapter), the version selector (versions stay on their
routes rather than being folded into the path), and middleware for an unknown
``operationId``. A JWT ``jwt_source`` that is not a URL is a shared secret and is redacted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical_model import CanonicalApi
from .gateway_config_model import (
    GatewayAuthHint,
    GatewayBackend,
    GatewayConfigDocument,
    GatewayConfigParseError,
    GatewayMatch,
    GatewayPathPattern,
    GatewayPlugin,
    GatewayRoute,
    GatewayServiceDef,
    redact_secret_config,
)
from .mesh_route_common import LimitCollector, path_pattern_for, policy_plugin, reject_binary
from .proxy_route_common import is_json_text, load_json_document, split_address, template_pattern

__all__ = [
    "TYK_FLAVOR",
    "TYK_OAS_EXTENSION",
    "TYK_PATH_RULES",
    "TYK_READ_CONSTRUCTS",
    "TYK_DECLARED_CONSTRUCTS",
    "has_tyk_extension",
    "interpret_tyk_oas",
    "is_tyk_classic_document",
    "is_tyk_policies_document",
    "load_tyk_json",
    "parse_tyk_classic",
    "policies_from",
]

#: Flavor key stamped on the parsed document.
TYK_FLAVOR = "tyk"

#: Human name used in messages.
_LABEL = "Tyk"

#: The OpenAPI extension that marks a Tyk OAS API definition.
TYK_OAS_EXTENSION = "x-tyk-api-gateway"

#: ``extended_paths`` lists whose entries are routes (with ``method_actions``).
_ROUTE_LISTS = ("white_list", "ignored")

#: ``extended_paths`` lists whose entries are per-path policy on a route.
TYK_PATH_RULES: Tuple[str, ...] = (
    "black_list",
    "cache",
    "hard_timeouts",
    "circuit_breakers",
    "url_rewrites",
    "transform",
    "transform_response",
    "transform_headers",
    "transform_response_headers",
    "transform_jq",
    "method_transforms",
    "size_limits",
    "validate_json",
    "validate_request",
    "virtual",
    "mock_response",
    "track_endpoints",
    "do_not_track_endpoints",
    "internal",
    "go_plugin",
    "persist_graphql",
    "rate_limit",
    "advance_cache_config",
)

#: Classic auth flags → canonical scheme (``None`` = an auth mechanism with no mapping).
_AUTH_FLAGS: Tuple[Tuple[str, Optional[str]], ...] = (
    ("use_oauth2", "oauth2"),
    ("use_openid", "openIdConnect"),
    ("enable_jwt", "bearer"),
    ("use_basic_auth", "basic"),
    ("use_mutual_tls_auth", "mutualTLS"),
    ("enable_signature_checking", None),
    ("use_go_plugin_auth", None),
    ("enable_coprocess_auth", None),
    ("use_standard_auth", "apiKey"),
)

#: API-level classic settings kept as global policy when set.
_GLOBAL_SETTINGS = ("global_rate_limit", "CORS", "cache_options", "response_processors", "custom_middleware")

#: Tyk OAS security-scheme blocks → canonical scheme.
_OAS_AUTH_KINDS: Dict[str, Optional[str]] = {
    "jwt": "bearer",
    "oauth": "oauth2",
    "basic": "basic",
    "hmac": None,
    "custom": None,
    "certificateAuth": "mutualTLS",
}

#: Construct vocabulary for the capability registry.
TYK_READ_CONSTRUCTS: Tuple[str, ...] = (
    "classic.proxy.listen_path",
    "classic.proxy.target_url",
    "classic.proxy.target_list",
    "classic.version_data",
    "classic.extended_paths.white_list",
    "classic.extended_paths.ignored",
    "classic.extended_paths.path-rules",
    "classic.auth-flags",
    "classic.global-settings",
    "policies.access_rights",
    "oas.openapi-document",
    "oas.x-tyk-api-gateway.server",
    "oas.x-tyk-api-gateway.upstream",
    "oas.x-tyk-api-gateway.middleware.global",
    "oas.x-tyk-api-gateway.middleware.operations",
    "policies-fileset",
)

#: Constructs declared on the ledger when a document uses them.
TYK_DECLARED_CONSTRUCTS: Tuple[str, ...] = (
    "graphql",
    "validate_json.schema",
    "version_selector",
    "custom_middleware.scripts",
    "middleware.operations.unknown-operation",
    "policies.other-api",
    "extended_paths.unknown-rule",
)

#: Path characters that make a Tyk path a pattern rather than a literal template.
_PATTERN_CHARS = re.compile(r"[*^$()|+?\[\]\\]")


# ---------------------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------------------


def has_tyk_extension(document: Any) -> bool:
    """True when ``document`` is an OpenAPI 3 document carrying ``x-tyk-api-gateway``."""
    return (
        isinstance(document, Mapping)
        and isinstance(document.get("openapi"), str)
        and isinstance(document.get(TYK_OAS_EXTENSION), Mapping)
    )


def _unwrap(document: Any) -> Any:
    """A Dashboard export wraps the definition in ``api_definition``; unwrap it."""
    if isinstance(document, Mapping) and isinstance(document.get("api_definition"), Mapping):
        return document["api_definition"]
    return document


def is_tyk_classic_document(document: Any) -> bool:
    """True when ``document`` is a classic API definition (``api_id`` + ``proxy``)."""
    document = _unwrap(document)
    return (
        isinstance(document, Mapping)
        and isinstance(document.get("api_id"), str)
        and isinstance(document.get("proxy"), Mapping)
    )


def is_tyk_policies_document(document: Any) -> bool:
    """True when ``document`` is a policies file (policies keyed by id, or a list)."""
    policies = document.values() if isinstance(document, Mapping) else document
    if not isinstance(policies, (list, type({}.values()))):
        return False
    items = list(policies)
    return bool(items) and all(
        isinstance(item, Mapping) and isinstance(item.get("access_rights"), Mapping) for item in items
    )


def load_tyk_json(text: str) -> Any:
    """Decode-check and load a classic definition or policies file.

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` / ``INPUT_MALFORMED`` /
            ``INPUT_TRUNCATED`` as for any JSON source; ``FORMAT_MISMATCH`` for text that
            is not JSON at all (a classic definition is always JSON).
    """
    reject_binary(text, format_label=_LABEL)
    if not is_json_text(text) and not text.lstrip().startswith("["):
        raise GatewayConfigParseError(
            "Not a Tyk API definition: a classic definition is a JSON object with `api_id` and "
            "`proxy`, and a Tyk OAS definition carries `x-tyk-api-gateway`",
            code="FORMAT_MISMATCH",
        )
    return load_json_document(text, format_label=_LABEL)


# ---------------------------------------------------------------------------------------
# Classic
# ---------------------------------------------------------------------------------------


def _join(listen_path: str, path: str) -> str:
    """The public path: ``listen_path`` + the entry path, one slash between them."""
    return "/" + "/".join(part.strip("/") for part in (listen_path, path) if part.strip("/"))


def _pattern(path: str) -> GatewayPathPattern:
    """A Tyk route path → pattern (``{param}`` templates, ``*`` / regex → regex)."""
    if _PATTERN_CHARS.search(path.replace("{", "").replace("}", "")):
        return path_pattern_for("RegularExpression", path.replace("*", ".*"))
    return template_pattern(path, "exact")


@dataclass
class _Rule:
    """One per-path policy rule waiting for its route."""

    kind: str
    path: str
    method: Optional[str]
    config: Dict[str, Any]


@dataclass
class _Version:
    """What one version contributes."""

    name: str
    routes: List[Tuple[str, Dict[str, Any], str]] = field(default_factory=list)
    rules: List[_Rule] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)
    plugins: List[Tuple[str, Any]] = field(default_factory=list)


def _versions(document: Mapping[str, Any]) -> List[Tuple[str, Mapping[str, Any]]]:
    """The versions to read.

    Raises:
        GatewayConfigParseError: ``INPUT_SEMANTIC_INVALID`` for a versioned API with no
            versions.
    """
    data = document.get("version_data") if isinstance(document.get("version_data"), Mapping) else {}
    versions = data.get("versions") if isinstance(data.get("versions"), Mapping) else {}
    not_versioned = data.get("not_versioned", True) is not False
    if not versions:
        if not_versioned:
            return [("Default", {})]
        raise GatewayConfigParseError(
            "The API is versioned (`not_versioned: false`) but `version_data.versions` is "
            "empty — no version exists, so no request can be served",
            code="INPUT_SEMANTIC_INVALID",
        )
    ordered = sorted(versions.items(), key=lambda item: str(item[0]))
    if not_versioned:
        default = data.get("default_version")
        chosen = next((item for item in ordered if item[0] == default), ordered[0])
        return [(str(chosen[0]), chosen[1] if isinstance(chosen[1], Mapping) else {})]
    return [(str(name), body if isinstance(body, Mapping) else {}) for name, body in ordered]


def _read_version(name: str, body: Mapping[str, Any], limits: LimitCollector) -> _Version:
    """Read one version's routes, per-path rules and version-level policy."""
    version = _Version(name=name)
    if isinstance(body.get("expires"), str) and body["expires"]:
        version.extras["expires"] = body["expires"]
    paths = body.get("extended_paths") if isinstance(body.get("extended_paths"), Mapping) else {}
    for list_name, entries in sorted(paths.items()):
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("path"), str):
                continue
            if list_name in _ROUTE_LISTS:
                actions = entry.get("method_actions") if isinstance(entry.get("method_actions"), Mapping) else {}
                version.routes.append((entry["path"], dict(actions), list_name))
                continue
            if list_name not in TYK_PATH_RULES:
                limits.add(
                    "extended_paths.unknown-rule",
                    "an extended_paths rule this reader does not know; it is kept as policy on the "
                    "API, not interpreted",
                )
            if list_name == "validate_json":
                limits.add(
                    "validate_json.schema",
                    "a validate_json request schema is carried as validation policy on its route, "
                    "not modelled as a message type — Tyk classic definitions carry no response "
                    "schemas, so the import does not claim schema fidelity",
                )
            config = {key: value for key, value in entry.items() if key not in ("path", "method")}
            if list_name == "black_list":
                config = {"method_actions": entry.get("method_actions")}
            method = entry.get("method")
            version.rules.append(
                _Rule(
                    kind=list_name,
                    path=entry["path"],
                    method=method.upper() if isinstance(method, str) else None,
                    config=config,
                )
            )
    for key in ("global_headers", "global_headers_remove", "global_response_headers", "global_size_limit"):
        if body.get(key):
            version.plugins.append((key, body[key]))
    return version


def _auth_hints(document: Mapping[str, Any], group: str) -> Tuple[List[GatewayAuthHint], int]:
    """Classic auth flags → auth hints (and how many secrets were redacted)."""
    if document.get("use_keyless") is True:
        return [], 0
    hints: List[GatewayAuthHint] = []
    redactions = 0
    configs = document.get("auth_configs") if isinstance(document.get("auth_configs"), Mapping) else {}
    for flag, scheme in _AUTH_FLAGS:
        if document.get(flag) is not True:
            continue
        detail: Dict[str, Any] = {"flag": flag}
        if flag == "enable_jwt":
            method = document.get("jwt_signing_method")
            source = document.get("jwt_source")
            if isinstance(method, str):
                detail["signing_method"] = method
            if isinstance(source, str) and source:
                if source.startswith(("http://", "https://")):
                    detail["jwks_url"] = source
                else:
                    detail["jwt_source"] = "***"
                    redactions += 1
        hints.append(GatewayAuthHint(scheme=scheme, plugin=flag, scope="service", attached_to=group, detail=detail))
    if not hints:
        token = configs.get("authToken") if isinstance(configs.get("authToken"), Mapping) else document.get("auth")
        header = token.get("auth_header_name") if isinstance(token, Mapping) else None
        hints.append(
            GatewayAuthHint(
                scheme="apiKey",
                plugin="auth_token",
                scope="service",
                attached_to=group,
                detail={"header": header} if isinstance(header, str) and header else {},
            )
        )
    return hints, redactions


def _policy_plugins(api_id: str, policies: Sequence[Mapping[str, Any]], limits: LimitCollector) -> List[GatewayPlugin]:
    """Policies granting access to ``api_id`` as consumer-scoped policy."""
    plugins: List[GatewayPlugin] = []
    for policy in policies:
        rights = policy.get("access_rights") if isinstance(policy.get("access_rights"), Mapping) else {}
        grant = rights.get(api_id)
        policy_id = str(policy.get("_id") or policy.get("id") or policy.get("name") or "policy")
        if not isinstance(grant, Mapping):
            limits.add(
                "policies.other-api",
                "a policy in the supplied policies file grants access only to other APIs; it is "
                "not attached to this one",
            )
            continue
        config = {
            key: policy[key]
            for key in ("rate", "per", "quota_max", "quota_renewal_rate", "throttle_interval")
            if key in policy
        }
        config["versions"] = grant.get("versions")
        config["allowed_urls"] = grant.get("allowed_urls")
        plugin, _count = policy_plugin("policy", config, scope="consumer", attached_to=policy_id)
        plugins.append(plugin)
    return sorted(plugins, key=lambda plugin: plugin.attached_to or "")


def parse_tyk_classic(
    document: Any,
    *,
    policies: Sequence[Mapping[str, Any]] = (),
    source_label: Optional[str] = None,
) -> GatewayConfigDocument:
    """Read a classic API definition into a gateway document.

    Args:
        document: The loaded definition (a Dashboard ``api_definition`` wrapper is accepted).
        policies: Policies from a policies file supplied alongside it.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="tyk"``).

    Raises:
        GatewayConfigParseError: ``FORMAT_MISMATCH`` when ``document`` is not a classic
            definition; ``INPUT_SEMANTIC_INVALID`` for a definition with no listen path or a
            versioned definition with no versions.
    """
    document = _unwrap(document)
    if not is_tyk_classic_document(document):
        raise GatewayConfigParseError(
            "Not a Tyk classic API definition (expected `api_id` and a `proxy` object)",
            code="FORMAT_MISMATCH",
        )
    proxy = document["proxy"]
    listen_path = proxy.get("listen_path")
    if not isinstance(listen_path, str) or not listen_path.strip():
        raise GatewayConfigParseError(
            f"API {document['api_id']!r} has no `proxy.listen_path` — Tyk mounts an API at its "
            "listen path, so without one no request reaches it",
            code="INPUT_SEMANTIC_INVALID",
        )
    limits = LimitCollector()
    api_id = document["api_id"]
    group = str(document.get("name") or api_id)
    hints, redactions = _auth_hints(document, group)

    global_plugins: List[GatewayPlugin] = []
    for key in _GLOBAL_SETTINGS:
        value = document.get(key)
        if key == "CORS" and not (isinstance(value, Mapping) and value.get("enable")):
            continue
        if key == "custom_middleware" and isinstance(value, Mapping):
            hooks = {hook: entries for hook, entries in value.items() if isinstance(entries, list) and entries}
            if not hooks:
                continue
            limits.add(
                "custom_middleware.scripts",
                "custom middleware runs JavaScript / plugin code on every request; its names are "
                "kept, what it does is not knowable from the definition",
            )
            value = {
                "hooks": {
                    hook: [entry.get("name") for entry in entries if isinstance(entry, Mapping)]
                    for hook, entries in hooks.items()
                }
            }
        if not value:
            continue
        plugin, count = policy_plugin(key, value, scope="global", attached_to=group)
        global_plugins.append(plugin)
        redactions += count
    global_plugins.extend(_policy_plugins(api_id, policies, limits))

    graphql = document.get("graphql") if isinstance(document.get("graphql"), Mapping) else {}
    if graphql.get("enabled"):
        limits.add(
            "graphql",
            "the API is a GraphQL proxy; its endpoint is imported as a route and its inline SDL "
            "is kept but not read as a schema — import the SDL with the GraphQL adapter",
        )
    definition = document.get("definition") if isinstance(document.get("definition"), Mapping) else {}
    data = document.get("version_data") if isinstance(document.get("version_data"), Mapping) else {}
    versioned = data.get("not_versioned") is False
    if versioned and definition:
        limits.add(
            "version_selector",
            "the version a request gets is chosen by a header, query parameter or URL segment "
            "at runtime; each version's routes carry the version name instead of a path change",
        )

    backends: List[GatewayBackend] = []
    targets = (
        proxy.get("target_list")
        if proxy.get("enable_load_balancing") and isinstance(proxy.get("target_list"), list)
        else [proxy.get("target_url")]
    )
    for target in targets:
        if isinstance(target, str) and target:
            host, _scheme, port = split_address(target)
            backends.append(GatewayBackend(name=host, port=port))

    routes: List[GatewayRoute] = []
    for version_name, body in _versions(document):
        version = _read_version(version_name, body, limits)
        version_plugins = []
        for key, value in version.plugins:
            plugin, count = policy_plugin(key, value, scope="route", attached_to=f"{api_id}@{version_name}")
            version_plugins.append(plugin)
            redactions += count
        route_paths = version.routes or [("", {}, "catch-all")]
        for path, actions, origin_list in route_paths:
            route_name = f"{api_id}@{version_name}{path or ':listen-path'}"
            public = _join(listen_path, path)
            pattern = _pattern(public) if path else path_pattern_for("PathPrefix", public)
            methods = sorted(str(method).upper() for method in actions) or [None]
            plugins = list(version_plugins)
            for rule in version.rules:
                if rule.path == path or (not version.routes and path == ""):
                    if rule.method is None or rule.method in methods or methods == [None]:
                        plugin, count = policy_plugin(
                            rule.kind,
                            {"path": rule.path, "method": rule.method, **rule.config},
                            scope="route",
                            attached_to=route_name,
                        )
                        plugins.append(plugin)
                        redactions += count
            extras: Dict[str, Any] = {
                "api_id": api_id,
                "api_version": version_name,
                "listen_path": listen_path,
                **version.extras,
            }
            if origin_list == "ignored":
                extras["auth_bypassed"] = True
            if versioned and definition:
                extras["version_selector"] = {
                    key: definition.get(key) for key in ("location", "key") if definition.get(key)
                }
            if actions:
                extras["method_actions"] = {
                    str(method).upper(): {key: value for key, value in spec.items() if key in ("action", "code")}
                    for method, spec in sorted(actions.items())
                    if isinstance(spec, Mapping)
                }
            if graphql.get("enabled"):
                extras["graphql"] = {
                    "execution_mode": graphql.get("execution_mode"),
                    "has_schema": bool(graphql.get("schema")),
                }
            routes.append(
                GatewayRoute(
                    name=route_name,
                    service_name=group,
                    hosts=(str(document["domain"]).lower(),)
                    if isinstance(document.get("domain"), str) and document["domain"]
                    else (),
                    matches=tuple(GatewayMatch(path=pattern, method=method) for method in methods),
                    auth=tuple(hints) if origin_list != "ignored" else (),
                    plugins=tuple(plugins),
                    backends=tuple(backends),
                    source_location=f"version_data.versions.{version_name}.extended_paths.{origin_list}"
                    if path
                    else "proxy.listen_path",
                    extras=extras,
                )
            )
        unattached = [
            rule
            for rule in version.rules
            if version.routes and not any(rule.path == route_path for route_path, _a, _o in version.routes)
        ]
        for rule in unattached:
            plugin, count = policy_plugin(
                rule.kind,
                {"path": rule.path, "method": rule.method, **rule.config},
                scope="service",
                attached_to=f"{api_id}@{version_name}",
            )
            global_plugins.append(plugin)
            redactions += count

    service = GatewayServiceDef(
        name=group,
        url=proxy.get("target_url") if isinstance(proxy.get("target_url"), str) else None,
        extras={
            "api_id": api_id,
            "listen_path": listen_path,
            "strip_listen_path": bool(proxy.get("strip_listen_path")),
            **({"targets": [t for t in targets if isinstance(t, str)]} if len(targets) > 1 else {}),
        },
    )
    return GatewayConfigDocument(
        flavor=TYK_FLAVOR,
        title=group,
        services=(service,),
        routes=tuple(routes),
        global_plugins=tuple(global_plugins),
        ignored=limits.as_ignored(),
        credential_redactions=redactions,
        source_label=source_label,
        raw={
            "flavor": TYK_FLAVOR,
            "form": "classic",
            "api_id": api_id,
            "listen_path": listen_path,
            "versions": sorted({route.extras["api_version"] for route in routes}),
            "route_names": sorted(route.name for route in routes),
            "policies": sorted(plugin.attached_to or "" for plugin in global_plugins if plugin.name == "policy"),
        },
    )


def policies_from(document: Any) -> List[Mapping[str, Any]]:
    """The policies of a policies file (keyed by id or a list)."""
    if isinstance(document, Mapping):
        return [value for value in document.values() if isinstance(value, Mapping)]
    if isinstance(document, list):
        return [value for value in document if isinstance(value, Mapping)]
    return []


# ---------------------------------------------------------------------------------------
# Tyk OAS
# ---------------------------------------------------------------------------------------


def _enabled_blocks(middleware: Any) -> Dict[str, Any]:
    """The enabled middleware blocks of a ``middleware.global`` / operation object."""
    if not isinstance(middleware, Mapping):
        return {}
    return {
        name: block
        for name, block in middleware.items()
        if not (isinstance(block, Mapping) and block.get("enabled") is False)
    }


def interpret_tyk_oas(model: CanonicalApi, document: Mapping[str, Any]) -> None:
    """Interpret ``x-tyk-api-gateway`` onto a model normalized from the OpenAPI document.

    The OpenAPI paths and schemas are as the document declares them. The gateway behaviour
    is added on top, each record stamped ``provenance: inferred`` — it is gateway policy read
    from the extension, not part of the API contract — and summarized in the same
    ``gateway`` report the classic form produces, so the ledger renders both forms alike.

    Args:
        model: The canonical model (mutated in place).
        document: The Tyk OAS document.
    """
    extension = document.get(TYK_OAS_EXTENSION) if isinstance(document.get(TYK_OAS_EXTENSION), Mapping) else {}
    limits = LimitCollector()
    redactions = 0
    middleware = extension.get("middleware") if isinstance(extension.get("middleware"), Mapping) else {}
    operations_mw = middleware.get("operations") if isinstance(middleware.get("operations"), Mapping) else {}
    by_operation_id: Dict[str, Any] = {}
    paths = document.get("paths") if isinstance(document.get("paths"), Mapping) else {}
    for path, item in paths.items():
        if not isinstance(item, Mapping):
            continue
        for method, op in item.items():
            if isinstance(op, Mapping) and isinstance(op.get("operationId"), str):
                for operation in model.operations():
                    if operation.http_method == str(method).upper() and operation.http_path == path:
                        by_operation_id.setdefault(op["operationId"], operation)

    plugin_rows: List[Tuple[str, str]] = []
    for operation_id, block in sorted(operations_mw.items()):
        operation = by_operation_id.get(str(operation_id))
        if operation is None:
            limits.add(
                "middleware.operations.unknown-operation",
                "middleware is keyed by an operationId the OpenAPI document does not declare; it "
                "applies to nothing and is not attached",
            )
            continue
        enabled = _enabled_blocks(block)
        redacted, count = redact_secret_config(enabled)
        redactions += count
        operation.extras["plugins"] = sorted(enabled)
        operation.extras["tyk"] = {"middleware": redacted, "provenance": "inferred"}
        plugin_rows.extend((name, "route") for name in enabled)

    global_mw = _enabled_blocks(middleware.get("global"))
    server = extension.get("server") if isinstance(extension.get("server"), Mapping) else {}
    upstream = extension.get("upstream") if isinstance(extension.get("upstream"), Mapping) else {}
    auth_rows = []
    authentication = server.get("authentication") if isinstance(server.get("authentication"), Mapping) else {}
    if authentication.get("enabled") is not False:
        schemes = (
            authentication.get("securitySchemes") if isinstance(authentication.get("securitySchemes"), Mapping) else {}
        )
        for name, scheme in sorted(schemes.items()):
            if not isinstance(scheme, Mapping) or scheme.get("enabled") is False:
                continue
            kind = next((key for key in _OAS_AUTH_KINDS if isinstance(scheme.get(key), Mapping)), None)
            auth_rows.append(
                {
                    "scheme": _OAS_AUTH_KINDS[kind] if kind else "apiKey",
                    "plugin": f"securitySchemes.{name}",
                    "scope": "global",
                    "attached_to": None,
                    "detail": {"kind": kind or "authToken"},
                }
            )
    upstream_policy = {
        name: block
        for name, block in upstream.items()
        if name not in ("url",) and not (isinstance(block, Mapping) and block.get("enabled") is False)
    }
    redacted_upstream, count = redact_secret_config(upstream_policy)
    redactions += count
    listen_path = server.get("listenPath") if isinstance(server.get("listenPath"), Mapping) else {}
    info = extension.get("info") if isinstance(extension.get("info"), Mapping) else {}
    model.extras["tyk"] = {
        "form": "oas",
        "provenance": "inferred",
        "api_id": info.get("id"),
        "listen_path": listen_path.get("value"),
        "upstream_url": upstream.get("url"),
        "upstream_policy": redacted_upstream,
        "global_middleware": sorted(global_mw),
    }
    schemaless = sum(1 for operation in model.operations() if not operation.messages)
    model.extras["gateway"] = {
        "flavor": TYK_FLAVOR,
        "route_count": len(model.operations()),
        "operation_count": len(model.operations()),
        "schemaless_operation_count": schemaless,
        "credential_redactions": redactions,
        "ignored_constructs": [dict(entry) for entry in limits.as_ignored()],
        "auth": [row for row in auth_rows if row["scheme"] is not None],
        "unmapped_plugins": [{"name": row["plugin"], "scope": "global"} for row in auth_rows if row["scheme"] is None],
        "global_plugins": sorted(global_mw),
        "unmodeled_plugins": [
            {"name": name, "scope": scope}
            for name, scope in sorted(
                set(plugin_rows)
                | {(name, "global") for name in global_mw}
                | {(name, "service") for name in upstream_policy}
            )
        ],
    }
