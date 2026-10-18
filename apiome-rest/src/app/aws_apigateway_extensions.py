"""AWS API Gateway export extensions: vocabulary, detection and interpretation — FMT-7.1 (#5455).

An exported API Gateway definition (``GetExport`` with ``extensions=apigateway`` for a REST API,
``ExportApi`` with ``includeExtensions`` for an HTTP API) is an ordinary OpenAPI (or Swagger 2.0)
document plus ``x-amazon-apigateway-*`` extensions. The extensions carry what the API actually
does — the backend each route calls, who may call it, what is validated, CORS — which a
hand-written spec usually omits.

This module is the pure half of the ``aws-apigateway`` adapter
(:mod:`app.aws_apigateway_import_source`): no parsing, no canonical-model construction, no I/O.

* :func:`has_aws_extensions` — the detection rule. It looks only where AWS writes extensions
  (the document root, servers, path items, operations and security schemes), never inside schemas
  or examples, so a plain OpenAPI document that merely *mentions* an AWS key in an example is not
  claimed. Detection must not be greedy: a document with no AWS extension belongs to the
  ``openapi`` adapter.
* :func:`integration_problems` — the semantic check: every integration must name a known ``type``.
* :func:`backend_for_integration`, :func:`security_for_scheme`, :func:`cors_from_mock_options`
  and :func:`validation_posture` — the interpretation of one extension each into the shape the
  canonical model records in ``extras``. Every record they return carries
  ``provenance: "declared"``: the export states these facts; nothing is inferred.
* :func:`extension_sites` — every ``x-*`` key in the document with its JSON Pointer, so a known
  extension the canonical model does not interpret, and an extension nobody has seen before, are
  both preserved and *reported* rather than dropped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

__all__ = [
    "ANY_METHOD",
    "AUTH",
    "AUTHORIZER",
    "AUTHTYPE",
    "CORS",
    "EXTENSION_PREFIX",
    "INTEGRATION",
    "INTEGRATION_TYPES",
    "INTERPRETED_EXTENSIONS",
    "PRESERVED_EXTENSIONS",
    "REQUEST_VALIDATOR",
    "REQUEST_VALIDATORS",
    "backend_for_integration",
    "cors_from_mock_options",
    "extension_sites",
    "has_aws_extensions",
    "integration_problems",
    "is_openapi_document",
    "security_for_scheme",
    "validation_posture",
]

EXTENSION_PREFIX = "x-amazon-apigateway-"

INTEGRATION = "x-amazon-apigateway-integration"
ANY_METHOD = "x-amazon-apigateway-any-method"
AUTH = "x-amazon-apigateway-auth"
AUTHORIZER = "x-amazon-apigateway-authorizer"
AUTHTYPE = "x-amazon-apigateway-authtype"
REQUEST_VALIDATOR = "x-amazon-apigateway-request-validator"
REQUEST_VALIDATORS = "x-amazon-apigateway-request-validators"
CORS = "x-amazon-apigateway-cors"
API_KEY_REQUIRED = "x-amazon-apigateway-api-key-required"

#: Extensions the adapter maps onto canonical constructs (backend, security, validation, CORS)
#: or onto operations (``any-method``).
INTERPRETED_EXTENSIONS = frozenset(
    {INTEGRATION, ANY_METHOD, AUTH, AUTHORIZER, AUTHTYPE, REQUEST_VALIDATOR, REQUEST_VALIDATORS, CORS, API_KEY_REQUIRED}
)

#: Documented AWS extensions the canonical model has no construct for. They are kept verbatim in
#: extras and listed on the coverage ledger as preserved, not interpreted.
PRESERVED_EXTENSIONS = frozenset(
    {
        "x-amazon-apigateway-api-key-source",
        "x-amazon-apigateway-binary-media-types",
        "x-amazon-apigateway-documentation",
        "x-amazon-apigateway-endpoint-configuration",
        "x-amazon-apigateway-gateway-responses",
        "x-amazon-apigateway-importexport-version",
        "x-amazon-apigateway-minimum-compression-size",
        "x-amazon-apigateway-policy",
        "x-amazon-apigateway-tag-value",
        "x-amazon-apigateway-security-policy",
        "x-amazon-apigateway-request-parameters",
    }
)

#: The integration types API Gateway accepts (REST and HTTP APIs), lower-cased.
INTEGRATION_TYPES = ("aws", "aws_proxy", "http", "http_proxy", "mock")

#: The HTTP methods OpenAPI path items can hold.
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace", "query")

#: Keys never descended into when looking for extension sites: their values are payload
#: descriptions or sample data, not API Gateway configuration.
_OPAQUE_KEYS = frozenset({"example", "examples", "schema", "schemas", "default", "enum", "const"})

#: Upper bound on nodes visited by :func:`extension_sites` (adversarial input stays linear).
_MAX_NODES = 200_000

_STAGE_VARIABLE = re.compile(r"\$\{stageVariables\.([A-Za-z0-9_]+)\}")
_ARN_SERVICE = re.compile(r"^arn:aws[a-z-]*:apigateway:[^:]*:([^:]+):")


def is_openapi_document(document: Any) -> bool:
    """True when ``document`` carries an OpenAPI 3.x or Swagger 2.0 version marker."""
    if not isinstance(document, Mapping):
        return False
    openapi, swagger = document.get("openapi"), document.get("swagger")
    return (isinstance(openapi, str) and openapi.startswith("3.")) or (
        isinstance(swagger, str) and swagger.startswith("2.")
    )


def _has_aws_key(node: Any) -> bool:
    return isinstance(node, Mapping) and any(isinstance(k, str) and k.startswith(EXTENSION_PREFIX) for k in node)


def _operations(document: Mapping[str, Any]) -> Iterator[Tuple[str, str, Mapping[str, Any]]]:
    """Every ``(path, method, operation)`` in the document, ``any-method`` included as ``any``."""
    paths = document.get("paths")
    if not isinstance(paths, Mapping):
        return
    for path, item in paths.items():
        if not isinstance(item, Mapping):
            continue
        for method in _HTTP_METHODS:
            if isinstance(item.get(method), Mapping):
                yield str(path), method, item[method]
        if isinstance(item.get(ANY_METHOD), Mapping):
            yield str(path), "any", item[ANY_METHOD]


def has_aws_extensions(document: Any) -> bool:
    """The detection rule: an OpenAPI/Swagger document with an AWS extension where AWS puts one.

    Looks at the document root, every server, every path item and operation, and every security
    scheme. Schemas and examples are never searched, so a plain OpenAPI document is never claimed.

    Args:
        document: The parsed document.

    Returns:
        ``True`` when the document is OpenAPI/Swagger and carries at least one
        ``x-amazon-apigateway-*`` extension in one of those places.
    """
    if not is_openapi_document(document):
        return False
    if _has_aws_key(document):
        return True
    for server in document.get("servers") or []:
        if _has_aws_key(server):
            return True
    paths = document.get("paths")
    if isinstance(paths, Mapping) and any(_has_aws_key(item) for item in paths.values()):
        return True
    if any(_has_aws_key(op) for _, _, op in _operations(document)):
        return True
    components = document.get("components") if isinstance(document.get("components"), Mapping) else {}
    schemes = components.get("securitySchemes") or document.get("securityDefinitions") or {}
    return isinstance(schemes, Mapping) and any(_has_aws_key(s) for s in schemes.values())


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def extension_sites(document: Any) -> List[Tuple[str, str]]:
    """Every ``x-*`` extension key in the document, with the JSON Pointer of its value.

    Extension values are not searched further (an extension's own keys are its payload), and
    neither are schemas or examples. The walk is iterative and bounded.

    Returns:
        ``(pointer, extension name)`` pairs in document order.
    """
    sites: List[Tuple[str, str]] = []
    stack: List[Tuple[str, Any]] = [("", document)]
    visited = 0
    while stack and visited < _MAX_NODES:
        pointer, node = stack.pop()
        visited += 1
        if isinstance(node, Mapping):
            children = []
            for key, value in node.items():
                child = f"{pointer}/{_escape(str(key))}"
                if isinstance(key, str) and key.startswith("x-"):
                    sites.append((child, key))
                elif str(key) not in _OPAQUE_KEYS:
                    children.append((child, value))
            stack.extend(reversed(children))
        elif isinstance(node, list):
            stack.extend(reversed([(f"{pointer}/{i}", v) for i, v in enumerate(node)]))
    return sites


def integration_problems(document: Mapping[str, Any]) -> List[str]:
    """The integrations that cannot be interpreted: not a mapping, no ``type``, unknown ``type``.

    Returns:
        One human sentence per problem (``GET /orders: …``); empty when every integration is fine.
    """
    problems: List[str] = []
    for path, method, op in _operations(document):
        if INTEGRATION not in op:
            continue
        where = f"{method.upper()} {path}"
        integration = op[INTEGRATION]
        if not isinstance(integration, Mapping):
            problems.append(f"{where}: {INTEGRATION} is not a mapping")
            continue
        kind = integration.get("type")
        if not isinstance(kind, str) or not kind.strip():
            problems.append(
                f"{where}: {INTEGRATION} declares no `type`, so the backend cannot be resolved "
                f"(expected one of {', '.join(INTEGRATION_TYPES)})"
            )
        elif kind.strip().lower() not in INTEGRATION_TYPES:
            problems.append(f"{where}: {INTEGRATION} has unknown type {kind!r}")
    return problems


def _stage_variables(*values: Any) -> List[str]:
    found = {m for v in values if isinstance(v, str) for m in _STAGE_VARIABLE.findall(v)}
    return sorted(found)


def backend_for_integration(integration: Mapping[str, Any]) -> Dict[str, Any]:
    """The canonical backend record for one ``x-amazon-apigateway-integration``.

    ``kind`` classifies the integration: ``lambda-proxy`` (``aws_proxy`` to Lambda), ``aws-proxy``
    (``aws_proxy`` to another service), ``aws-service`` (``aws``, with the service named from the
    ARN), ``http-proxy``, ``http`` or ``mock``. Templates and parameter mappings are not repeated
    here; the verbatim integration rides beside it.

    Args:
        integration: A valid integration (see :func:`integration_problems`).

    Returns:
        ``{kind, type, uri?, httpMethod?, connectionType?, connectionId?, payloadFormatVersion?,
        timeoutInMillis?, service?, stageVariables?, provenance: "declared"}``.
    """
    kind_raw = str(integration.get("type")).strip().lower()
    uri = integration.get("uri") if isinstance(integration.get("uri"), str) else None
    if kind_raw == "aws_proxy":
        kind = "lambda-proxy" if uri and (":lambda:" in uri) else "aws-proxy"
    elif kind_raw == "aws":
        kind = "aws-service"
    else:
        kind = kind_raw.replace("_", "-")
    backend: Dict[str, Any] = {"kind": kind, "type": kind_raw}
    for key in ("uri", "httpMethod", "connectionType", "connectionId", "payloadFormatVersion", "timeoutInMillis"):
        if integration.get(key) is not None:
            backend[key] = integration[key]
    if kind_raw == "aws" and uri:
        match = _ARN_SERVICE.match(uri)
        if match:
            backend["service"] = match.group(1)
    stage_vars = _stage_variables(uri, integration.get("connectionId"))
    if stage_vars:
        backend["stageVariables"] = stage_vars
    backend["provenance"] = "declared"
    return backend


def security_for_scheme(name: str, scheme: Mapping[str, Any], scopes: List[Any]) -> Dict[str, Any]:
    """The canonical security record for one requirement on a declared security scheme.

    The canonical scheme identifier follows :mod:`app.canonical_security`: ``awsSigv4`` for IAM
    (``authtype: awsSigv4``), ``bearer`` for a JWT authorizer or an HTTP bearer scheme,
    ``authorization`` for an ``Authorization``-header API key (Lambda token/request and Cognito
    authorizers), ``apiKey`` for any other API key, and the OpenAPI type otherwise.

    Args:
        name: The scheme's name under ``components.securitySchemes``.
        scheme: The Security Scheme Object.
        scopes: The scopes the requirement asks for.

    Returns:
        ``{scheme, name, scopes, in?, parameterName?, authType?, authorizer?, provenance}``.
    """
    authorizer = scheme.get(AUTHORIZER) if isinstance(scheme.get(AUTHORIZER), Mapping) else None
    auth_type = scheme.get(AUTHTYPE) if isinstance(scheme.get(AUTHTYPE), str) else None
    openapi_type = str(scheme.get("type") or "")
    authorizer_type = str((authorizer or {}).get("type") or "").lower()
    if (auth_type or "").lower() in ("awssigv4", "aws_iam"):
        canonical = "awsSigv4"
    elif authorizer_type == "jwt":
        canonical = "bearer"
    elif openapi_type == "http":
        canonical = str(scheme.get("scheme") or "http").lower()
    elif openapi_type == "apiKey":
        header = str(scheme.get("name") or "")
        canonical = "authorization" if header.lower() == "authorization" and scheme.get("in") == "header" else "apiKey"
    else:
        canonical = openapi_type or "unknown"
    record: Dict[str, Any] = {"scheme": canonical, "name": name, "scopes": [str(s) for s in scopes or []]}
    if openapi_type == "apiKey":
        record["in"] = scheme.get("in")
        record["parameterName"] = scheme.get("name")
    if auth_type:
        record["authType"] = auth_type
    if authorizer is not None:
        record["authorizer"] = dict(authorizer)
    record["provenance"] = "declared"
    return record


def _header_values(value: Any) -> Optional[str]:
    """A mapping-expression literal (``"'GET,POST'"``) as its plain value, else ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1]
    return None


def cors_from_mock_options(integration: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """CORS a REST API declares the classic way: a mock ``OPTIONS`` integration's response headers.

    Returns:
        ``{allowOrigins, allowMethods, allowHeaders, source: "mock-integration", provenance}`` for
        the ``Access-Control-Allow-*`` literals found, or ``None`` when there are none.
    """
    if str(integration.get("type") or "").lower() != "mock":
        return None
    found: Dict[str, List[str]] = {}
    responses = integration.get("responses") if isinstance(integration.get("responses"), Mapping) else {}
    for response in responses.values():
        params = response.get("responseParameters") if isinstance(response, Mapping) else None
        if not isinstance(params, Mapping):
            continue
        for key, value in params.items():
            header = str(key).rsplit(".", 1)[-1].lower()
            literal = _header_values(value)
            if literal is None or not header.startswith("access-control-allow-"):
                continue
            field = {
                "access-control-allow-origin": "allowOrigins",
                "access-control-allow-methods": "allowMethods",
                "access-control-allow-headers": "allowHeaders",
                "access-control-allow-credentials": "allowCredentials",
            }.get(header)
            if field:
                found.setdefault(field, []).extend(p.strip() for p in literal.split(",") if p.strip())
    if not found:
        return None
    cors: Dict[str, Any] = {k: sorted(set(v)) for k, v in found.items() if k != "allowCredentials"}
    if "allowCredentials" in found:
        cors["allowCredentials"] = "true" in [v.lower() for v in found["allowCredentials"]]
    cors["source"] = "mock-integration"
    cors["provenance"] = "declared"
    return cors


def validation_posture(name: Optional[str], validators: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The declared request-validation posture for one operation.

    Args:
        name: The validator the operation (or the API default) names, if any.
        validators: ``x-amazon-apigateway-request-validators``.

    Returns:
        ``{validator, validateRequestBody, validateRequestParameters, defined, provenance}``, or
        ``None`` when no validator applies. ``defined`` is ``False`` when the name has no entry in
        ``validators`` (both flags are then unknown and recorded as ``None``).
    """
    if not isinstance(name, str) or not name:
        return None
    entry = validators.get(name) if isinstance(validators, Mapping) else None
    defined = isinstance(entry, Mapping)
    return {
        "validator": name,
        "validateRequestBody": bool(entry.get("validateRequestBody")) if defined else None,
        "validateRequestParameters": bool(entry.get("validateRequestParameters")) if defined else None,
        "defined": defined,
        "provenance": "declared",
    }
