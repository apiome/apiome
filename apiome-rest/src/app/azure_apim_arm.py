"""Azure API Management ARM templates: resource reading and definition synthesis — FMT-7.2 (#5456).

An APIM estate exported as an ARM deployment template lists one resource per entity:
``Microsoft.ApiManagement/service/apis`` (the API and its gateway path, backend URL and
subscription-key posture), ``…/apis/operations`` (method, URL template, parameters, responses),
``…/apis/policies`` and ``…/apis/operations/policies`` (the policy XML as an escaped string),
``…/products`` (+ ``…/products/apis`` links and ``…/products/policies``), ``…/backends``,
``…/namedValues``, ``…/apiVersionSets`` and the service-wide ``…/policies``.

This module is pure: :func:`read_arm_template` collects those resources into an
:class:`ArmEstate`, and :func:`openapi_for_estate` writes the operations as one OpenAPI 3.0
document — the shape APIM's own OpenAPI export has — so the definition half is normalized by the
OpenAPI path exactly as an exported definition would be.

**Paths.** When only one API carries operations, the document mirrors APIM's export: the server
is ``https://{service}.azure-api.net/{apiPath}`` and the paths are the operations' URL templates.
When several do, the server is the gateway host and each path is prefixed with the API's path
(and, for ``Segment``-versioned APIs, its version), which is the URL a caller actually sends. A SOAP
pass-through operation, whose URL template is usually ``/`` for every operation, is told apart by
its ``SOAPAction`` the way APIM's export does it: ``/?soapAction={action}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "ARM_TYPE_PREFIX",
    "ArmApi",
    "ArmEstate",
    "SUBSCRIPTION_KEY_HEADER",
    "has_apim_markers",
    "is_apim_arm_template",
    "openapi_for_estate",
    "read_arm_template",
]

#: Resource-type prefix of every APIM resource (compared case-insensitively, as ARM does).
ARM_TYPE_PREFIX = "microsoft.apimanagement/service"

_PARAM_RE = re.compile(r"parameters\(\s*'([^']*)'\s*\)")
_LITERAL_RE = re.compile(r"'((?:[^']|'')*)'")
_SIMPLE_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
_LINK_FORMATS = {"xml-link", "rawxml-link"}

#: The subscription-key header APIM writes into every exported definition it secures.
SUBSCRIPTION_KEY_HEADER = "Ocp-Apim-Subscription-Key"
#: Host suffix of an APIM gateway (``{service}.azure-api.net``).
GATEWAY_HOST_SUFFIX = ".azure-api.net"


@dataclass
class ArmApi:
    """One ``…/apis`` resource with the operations and policies that hang off it.

    Attributes:
        name: The API's resource name (``orders-api``).
        properties: The API resource's ``properties``.
        operations: ``(operation name, properties)`` in template order.
        policy: The API-scope policy XML, when the template carries one.
        operation_policies: Operation name → operation-scope policy XML.
    """

    name: str
    properties: Dict[str, Any]
    operations: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    policy: Optional[str] = None
    operation_policies: Dict[str, str] = field(default_factory=dict)


@dataclass
class ArmEstate:
    """Every APIM resource an ARM template declares.

    Attributes:
        service: The APIM service name (from the resource names, parameters resolved to their
            ``defaultValue``), or ``None`` when no resource names it.
        apis: The APIs, in template order.
        products: Product name → ``{"properties", "apis", "policy"}``.
        backends: Backend id → ``{"url", "protocol"}``.
        named_values: Named-value names (values are never read: they may be secrets).
        version_sets: Version-set name → properties.
        global_policy: The service-wide policy XML, when present.
        linked_policies: ``{"resource", "format"}`` for every policy given only as a link
            (``xml-link``), which an import cannot fetch.
    """

    service: Optional[str] = None
    apis: List[ArmApi] = field(default_factory=list)
    products: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    backends: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    named_values: List[str] = field(default_factory=list)
    version_sets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    global_policy: Optional[str] = None
    linked_policies: List[Dict[str, str]] = field(default_factory=list)


def is_apim_arm_template(document: Any) -> bool:
    """Whether ``document`` is an ARM template declaring at least one APIM resource."""
    if not isinstance(document, Mapping) or not isinstance(document.get("resources"), list):
        return False
    return any(_type_of(r, "").startswith(ARM_TYPE_PREFIX) for r in _flatten(document["resources"]))


def has_apim_markers(document: Any) -> bool:
    """Whether an OpenAPI/Swagger document is an APIM export.

    APIM writes its subscription key into every definition it exports — an ``apiKey`` security
    scheme on the ``Ocp-Apim-Subscription-Key`` header — and serves it from a
    ``{service}.azure-api.net`` gateway. Either marker is evidence the document came from APIM; a
    plain OpenAPI document carries neither, and stays with the ``openapi`` adapter.
    """
    if not isinstance(document, Mapping):
        return False
    components = document.get("components") if isinstance(document.get("components"), Mapping) else {}
    schemes = components.get("securitySchemes") or document.get("securityDefinitions") or {}
    if isinstance(schemes, Mapping):
        for scheme in schemes.values():
            if (
                isinstance(scheme, Mapping)
                and scheme.get("type") == "apiKey"
                and str(scheme.get("name") or "").lower() == SUBSCRIPTION_KEY_HEADER.lower()
            ):
                return True
    hosts = [str(s.get("url") or "") for s in document.get("servers") or [] if isinstance(s, Mapping)]
    if isinstance(document.get("host"), str):
        hosts.append(document["host"])
    for url in hosts:
        host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
        if host.endswith(GATEWAY_HOST_SUFFIX):
            return True
    return False


def read_arm_template(document: Mapping[str, Any]) -> ArmEstate:
    """Collect the APIM resources of an ARM template.

    Args:
        document: The parsed template (``resources`` may nest child ``resources``).

    Returns:
        The :class:`ArmEstate`. Resources of other providers are ignored.
    """
    defaults = _parameter_defaults(document)
    estate = ArmEstate()
    apis: Dict[str, ArmApi] = {}
    pending_ops: List[Tuple[str, str, Dict[str, Any]]] = []
    pending_op_policies: List[Tuple[str, str, str]] = []
    product_links: List[Tuple[str, str]] = []

    for resource in _flatten(document.get("resources") or []):
        rtype = _type_of(resource, "")
        if not rtype.startswith(ARM_TYPE_PREFIX):
            continue
        kind = rtype[len(ARM_TYPE_PREFIX) :].strip("/")
        segments = _name_segments(str(resource.get("name") or ""), defaults)
        if segments and estate.service is None:
            estate.service = segments[0]
        names = segments[1:]
        props = resource.get("properties") if isinstance(resource.get("properties"), Mapping) else {}
        props = dict(props)
        if kind == "apis" and names:
            apis.setdefault(names[0], ArmApi(names[0], props)).properties = props
        elif kind == "apis/operations" and len(names) >= 2:
            pending_ops.append((names[0], names[1], props))
        elif kind == "apis/policies" and names:
            xml = _policy_value(props, rtype, estate)
            if xml is not None:
                apis.setdefault(names[0], ArmApi(names[0], {})).policy = xml
        elif kind == "apis/operations/policies" and len(names) >= 2:
            xml = _policy_value(props, rtype, estate)
            if xml is not None:
                pending_op_policies.append((names[0], names[1], xml))
        elif kind == "products" and names:
            estate.products.setdefault(names[0], {"apis": [], "policy": None})["properties"] = props
        elif kind == "products/apis" and len(names) >= 2:
            product_links.append((names[0], names[1]))
        elif kind == "products/policies" and names:
            estate.products.setdefault(names[0], {"apis": [], "policy": None, "properties": {}})["policy"] = (
                _policy_value(props, rtype, estate)
            )
        elif kind == "backends" and names:
            estate.backends[names[0]] = {"url": props.get("url"), "protocol": props.get("protocol")}
        elif kind in ("namedvalues", "properties") and names:
            estate.named_values.append(names[0])
            display = props.get("displayName")
            if isinstance(display, str) and display != names[0]:
                estate.named_values.append(display)
        elif kind == "apiversionsets" and names:
            estate.version_sets[names[0]] = props
        elif kind == "policies":
            estate.global_policy = _policy_value(props, rtype, estate)

    for api_name, op_name, props in pending_ops:
        apis.setdefault(api_name, ArmApi(api_name, {})).operations.append((op_name, props))
    for api_name, op_name, xml in pending_op_policies:
        apis.setdefault(api_name, ArmApi(api_name, {})).operation_policies[op_name] = xml
    for product, api_name in product_links:
        estate.products.setdefault(product, {"apis": [], "policy": None, "properties": {}})["apis"].append(api_name)
    estate.apis = list(apis.values())
    estate.named_values = sorted(set(estate.named_values))
    return estate


def openapi_for_estate(estate: ArmEstate) -> Tuple[Dict[str, Any], Dict[Tuple[str, str], Tuple[str, str]], List[str]]:
    """Write the estate's operations as one OpenAPI 3.0 document (see the module docstring).

    Args:
        estate: From :func:`read_arm_template`.

    Returns:
        ``(document, owners, collisions)`` — the OpenAPI document; ``(METHOD, path)`` → ``(api name,
        operation name)`` for every written operation, so policies can be attached to it; and a
        description of every operation skipped because another API already answers the same
        method and path.
    """
    with_ops = [api for api in estate.apis if api.operations]
    single = len(with_ops) <= 1
    primary = with_ops[0] if with_ops else _current_api(estate.apis)
    host = f"https://{estate.service or 'apim'}.azure-api.net"
    props = primary.properties if primary else {}

    info: Dict[str, Any] = {
        "title": (props.get("displayName") if single else None) or estate.service or "Azure API Management",
        "version": str(props.get("apiVersion") or props.get("apiRevision") or "1") if single else "1",
    }
    if single and props.get("description"):
        info["description"] = props["description"]
    server_path = str(props.get("path") or "").strip("/") if single else ""
    document: Dict[str, Any] = {
        "openapi": "3.0.1",
        "info": info,
        "servers": [{"url": f"{host}/{server_path}" if server_path else host}],
        "paths": {},
    }
    schemes: Dict[str, Dict[str, Any]] = {}
    owners: Dict[Tuple[str, str], Tuple[str, str]] = {}
    collisions: List[str] = []

    for api in with_ops:
        prefix = "" if single else _api_prefix(api, estate)
        security = _subscription_security(api.properties, schemes)
        soap = str(api.properties.get("apiType") or api.properties.get("type") or "").lower() == "soap"
        for op_name, op_props in api.operations:
            method = str(op_props.get("method") or "GET").upper()
            path = _join(prefix, str(op_props.get("urlTemplate") or "/"))
            action = _soap_action(op_props) if soap else None
            if action:
                path = f"{path}?soapAction={action}"
            if (method, path) in owners:
                collisions.append(f"{method} {path} ({api.name}/{op_name})")
                continue
            owners[(method, path)] = (api.name, op_name)
            operation = _operation(op_name, op_props)
            if security is not None:
                operation["security"] = security
            if not single:
                operation["tags"] = [str(api.properties.get("displayName") or api.name)]
            document["paths"].setdefault(path, {})[method.lower()] = operation
    if schemes:
        document["components"] = {"securitySchemes": schemes}
    return document, owners, collisions


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _flatten(resources: List[Any], parent_type: str = "", parent_name: str = "") -> List[Dict[str, Any]]:
    """Every resource, nested child ``resources`` included with their full type and name."""
    out: List[Dict[str, Any]] = []
    for resource in resources:
        if not isinstance(resource, Mapping):
            continue
        rtype = str(resource.get("type") or "")
        name = str(resource.get("name") or "")
        if parent_type and "/" not in rtype.strip("/"):
            rtype = f"{parent_type}/{rtype}"
            name = f"{parent_name}/{name}" if not name.startswith("[") else name
        flat = {**resource, "type": rtype, "name": name}
        out.append(flat)
        children = resource.get("resources")
        if isinstance(children, list):
            out.extend(_flatten(children, rtype, name))
    return out


def _type_of(resource: Mapping[str, Any], default: str) -> str:
    rtype = resource.get("type")
    return rtype.strip().lower() if isinstance(rtype, str) else default


def _parameter_defaults(document: Mapping[str, Any]) -> Dict[str, str]:
    params = document.get("parameters") if isinstance(document.get("parameters"), Mapping) else {}
    return {
        str(k): str(v["defaultValue"])
        for k, v in params.items()
        if isinstance(v, Mapping) and isinstance(v.get("defaultValue"), (str, int, float))
    }


def _name_segments(name: str, defaults: Mapping[str, str]) -> List[str]:
    """The ``/``-separated segments of a resource name, ARM ``concat``/``parameters`` resolved.

    ``[concat(parameters('ApimServiceName'), '/orders-api')]`` with ``ApimServiceName`` defaulting
    to ``example-apim`` gives ``["example-apim", "orders-api"]``; a parameter with no default stays
    as ``{ApimServiceName}``.
    """
    text = name.strip()
    if text.startswith("[") and text.endswith("]"):
        expression = _PARAM_RE.sub(lambda m: "'" + defaults.get(m.group(1), "{" + m.group(1) + "}") + "'", text[1:-1])
        text = "".join(m.group(1).replace("''", "'") for m in _LITERAL_RE.finditer(expression))
    return [segment for segment in text.split("/") if segment]


def _policy_value(props: Mapping[str, Any], rtype: str, estate: ArmEstate) -> Optional[str]:
    fmt = str(props.get("format") or "xml").lower()
    value = props.get("value") if isinstance(props.get("value"), str) else props.get("policyContent")
    if fmt in _LINK_FORMATS:
        estate.linked_policies.append({"resource": rtype, "format": fmt})
        return None
    return value if isinstance(value, str) and value.strip() else None


def _current_api(apis: List[ArmApi]) -> Optional[ArmApi]:
    for api in apis:
        if api.properties.get("isCurrent") is True:
            return api
    return apis[0] if apis else None


def _api_prefix(api: ArmApi, estate: ArmEstate) -> str:
    path = str(api.properties.get("path") or "").strip("/")
    prefix = f"/{path}" if path else ""
    version_set = estate.version_sets.get(str(api.properties.get("apiVersionSetId") or "").rsplit("/", 1)[-1])
    version = api.properties.get("apiVersion")
    if version and isinstance(version_set, Mapping) and str(version_set.get("versioningScheme")).lower() == "segment":
        prefix = f"{prefix}/{version}"
    return prefix


def _join(prefix: str, template: str) -> str:
    template = "/" + template.lstrip("/")
    if not prefix:
        return template
    return prefix if template == "/" else prefix + template


def _soap_action(op_props: Mapping[str, Any]) -> Optional[str]:
    request = op_props.get("request") if isinstance(op_props.get("request"), Mapping) else {}
    for header in request.get("headers") or []:
        if isinstance(header, Mapping) and str(header.get("name") or "").lower() == "soapaction":
            value = str(header.get("defaultValue") or "").strip().strip('"')
            return value or None
    return None


def _subscription_security(
    props: Mapping[str, Any], schemes: Dict[str, Dict[str, Any]]
) -> Optional[List[Dict[str, List[str]]]]:
    """APIM's subscription-key requirement, as its export writes it (``apiKeyHeader`` / ``apiKeyQuery``)."""
    if props.get("subscriptionRequired") is not True:
        return None
    names = (
        props.get("subscriptionKeyParameterNames")
        if isinstance(props.get("subscriptionKeyParameterNames"), Mapping)
        else {}
    )
    requirement: List[Dict[str, List[str]]] = []
    for where, default, base in (
        ("header", "Ocp-Apim-Subscription-Key", "apiKeyHeader"),
        ("query", "subscription-key", "apiKeyQuery"),
    ):
        param = str(names.get(where) or default)
        scheme = {"type": "apiKey", "name": param, "in": where}
        key = base
        suffix = 2
        while key in schemes and schemes[key] != scheme:
            key = f"{base}{suffix}"
            suffix += 1
        schemes[key] = scheme
        requirement.append({key: []})
    return requirement


def _parameter(param: Mapping[str, Any], location: str) -> Dict[str, Any]:
    ptype = str(param.get("type") or "string").lower()
    schema: Dict[str, Any] = {"type": ptype if ptype in _SIMPLE_TYPES else "string"}
    default = param.get("defaultValue")
    if default is not None and default != "":
        schema["default"] = _coerce(default, schema["type"])
    values = param.get("values")
    if isinstance(values, list) and values:
        schema["enum"] = [_coerce(v, schema["type"]) for v in values]
    out: Dict[str, Any] = {
        "name": str(param.get("name")),
        "in": location,
        "required": True if location == "path" else bool(param.get("required")),
        "schema": schema,
    }
    if param.get("description"):
        out["description"] = param["description"]
    return out


def _coerce(value: Any, ptype: str) -> Any:
    if ptype in ("integer", "number") and isinstance(value, str):
        try:
            return int(value) if ptype == "integer" else float(value)
        except ValueError:
            return value
    if ptype == "boolean" and isinstance(value, str):
        return value.strip().lower() == "true"
    return value


def _content(representations: Any) -> Dict[str, Any]:
    content: Dict[str, Any] = {}
    for rep in representations or []:
        if isinstance(rep, Mapping) and rep.get("contentType"):
            content[str(rep["contentType"])] = {}
    return content


def _operation(op_name: str, props: Mapping[str, Any]) -> Dict[str, Any]:
    """One APIM operation resource as an OpenAPI Operation Object."""
    operation: Dict[str, Any] = {"operationId": op_name}
    if props.get("displayName"):
        operation["summary"] = props["displayName"]
    if props.get("description"):
        operation["description"] = props["description"]
    request = props.get("request") if isinstance(props.get("request"), Mapping) else {}
    parameters = [_parameter(p, "path") for p in props.get("templateParameters") or [] if isinstance(p, Mapping)]
    parameters += [_parameter(p, "query") for p in request.get("queryParameters") or [] if isinstance(p, Mapping)]
    parameters += [_parameter(p, "header") for p in request.get("headers") or [] if isinstance(p, Mapping)]
    if parameters:
        operation["parameters"] = parameters
    body = _content(request.get("representations"))
    if body:
        operation["requestBody"] = {"content": body}
    responses: Dict[str, Any] = {}
    for response in props.get("responses") or []:
        if not isinstance(response, Mapping) or response.get("statusCode") is None:
            continue
        entry: Dict[str, Any] = {"description": str(response.get("description") or "")}
        content = _content(response.get("representations"))
        if content:
            entry["content"] = content
        responses[str(response["statusCode"])] = entry
    operation["responses"] = responses
    return operation
