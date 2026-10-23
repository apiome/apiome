"""Reader for SoapUI / ReadyAPI project XML — FMT-10.3 (#5477).

A SoapUI project (``<con:soapui-project>`` in the ``http://eviware.com/soapui/config`` namespace,
also what SmartBear ReadyAPI saves) is where a SOAP estate keeps its request corpus and its test
suites. One file holds:

* ``interface`` elements — a **WSDL-backed** interface (``xsi:type="con:WsdlInterface"``) names a
  WSDL ``definition`` and its binding's ``operation`` elements; a **REST** interface
  (``xsi:type="con:RestService"``) holds nested ``resource`` / ``method`` elements with
  ``parameter`` definitions (``QUERY``, ``TEMPLATE``, ``HEADER``, ``MATRIX``) and saved
  ``request`` elements;
* ``testSuite`` / ``testCase`` / ``testStep`` / ``assertion`` structures;
* ``restMockService`` canned responses, project ``properties`` and ``environments``.

This module reads all of that into a :class:`SoapUiDocument` — it never builds the canonical model
itself (:mod:`app.soapui_normalizer` does):

* **WSDL interfaces delegate to the WSDL adapter.** The WSDL a WSDL interface names is located —
  in the project's own ``definitionCache`` (where SoapUI keeps a copy of every WSDL and XSD part),
  else among the fileset members uploaded beside the project — and parsed by
  :func:`app.wsdl_parser.parse_wsdl`, so the schema fidelity is exactly the WSDL adapter's. A WSDL
  the project only *links to* (an ``https://…?wsdl`` URL with an empty cache) is never fetched; its
  operations are still declared from the project, without schemas. A *local* WSDL file that is
  neither cached nor uploaded is an unresolved reference.
* **REST interfaces feed the inferred-spec engine.** Every saved request (and every method without
  one) becomes a concrete :class:`~app.inferred_spec.HttpObservation`; mock responses become
  response-only observations of the method they answer.
* **Test suites are read as declared test intent** — suites, cases, steps and assertion kinds, each
  request step's target named so the normalizer can link it to an operation.

**Credentials never leave this module.** ``credentials`` blocks are read for their ``authType`` and
``wssType`` only — usernames, passwords and domains are never read. Every other value that reaches
an observation (URLs, parameter and header values, bodies, property defaults) passes the shared
secret-scrub gate first, and a value whose *name* says it is a secret is redacted outright.
Groovy scripts are never read.

Error codes (the import taxonomy):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD or a byte-order mark (a UTF-16 upload read as UTF-8).
* ``INPUT_TRUNCATED`` — the XML ends while an element or attribute is still open.
* ``INPUT_MALFORMED`` — any other XML syntax error, or a REST method without an HTTP verb.
* ``FORMAT_MISMATCH`` — XML (or text) that is not a SoapUI project (a bare WSDL, a WADL …).
* ``INPUT_SEMANTIC_INVALID`` — a project with no interfaces or mock services, or whose interfaces
  declare no operations.
* ``INPUT_REFERENCE_UNRESOLVED`` — a WSDL interface whose local ``definition`` file is neither in
  the project's ``definitionCache`` nor among the uploaded files.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .client_collection import SECRET_NAME_RE, scrub_named, scrub_value
from .device_model_xml import (
    DeviceModelXmlError,
    child,
    child_text,
    children,
    local_name,
    read_device_model_xml,
    root_element_name,
)
from .inferred_spec import HttpObservation
from .secure_xml import SecureXmlError, parse_xml
from .wsdl_parser import WsdlDocument, WsdlParseError, is_wsdl, parse_wsdl

__all__ = [
    "AUTH_SCHEMES",
    "FORMAT_KEY",
    "SOAPUI_NAMESPACE",
    "SoapUiAuth",
    "SoapUiCall",
    "SoapUiDocument",
    "SoapUiOperation",
    "SoapUiParseError",
    "SoapUiProperty",
    "SoapUiRequest",
    "SoapUiStep",
    "SoapUiWsdlInterface",
    "is_soapui_project",
    "parse_soapui_fileset",
    "parse_soapui_text",
]

#: The registry key of the format.
FORMAT_KEY = "soapui"

#: The namespace every SoapUI and ReadyAPI project element lives in.
SOAPUI_NAMESPACE = "http://eviware.com/soapui/config"

_ROOT = "soapui-project"

#: SoapUI ``authType`` (lower-cased) → the canonical scheme :mod:`app.canonical_security` reads.
#: Negotiated schemes (NTLM, Kerberos) and OAuth 1 have no canonical scheme of their own and are a
#: generic ``authorization`` requirement. Types not listed (``No Authorization``, ``Global HTTP
#: Settings``) mean no auth of the request's own.
AUTH_SCHEMES: Mapping[str, str] = {
    "basic": "basic",
    "preemptive": "basic",
    "digest": "digest",
    "ntlm": "authorization",
    "spnego/kerberos": "authorization",
    "kerberos": "authorization",
    "oauth 1.0": "authorization",
    "oauth 2.0": "oauth2",
    "oauth 2": "oauth2",
}

#: A whole ``${…}`` property expansion — kept as written, never scrubbed (it is a reference).
_WHOLE_EXPANSION_RE = re.compile(r"^\s*\$\{[^}]*\}\s*$")
#: Any ``${…}`` property expansion.
_EXPANSION_RE = re.compile(r"\$\{([^}]*)\}")
#: A ``${…}`` written as a bare JSON value (``"qty": ${qty}``), which makes a body unparseable.
_BARE_JSON_EXPANSION_RE = re.compile(r'(?<!")(\$\{[^}]*\})(?!")')
#: Scopes a ``${#Scope#name}`` expansion may name; only ``Project`` (and an unscoped name) resolve
#: against the project's own properties.
_PROJECT_SCOPES = frozenset({"project", ""})
_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_.\-]+")

#: Parameter styles SoapUI declares, and where each one goes on a request.
_QUERY, _TEMPLATE, _HEADER, _MATRIX = "QUERY", "TEMPLATE", "HEADER", "MATRIX"

#: The step types that send a request, and the config attributes / elements naming their target.
_REST_STEP_TYPES = frozenset({"restrequest"})
_SOAP_STEP_TYPES = frozenset({"request"})

#: Assertion configuration elements kept as declared expectations, and the key each is kept under.
#: (SoapUI's *Contains* assertion calls its expected text ``token``; it is kept as ``expected``.)
_ASSERTION_FACTS: Mapping[str, str] = {
    "codes": "codes",
    "path": "path",
    "content": "expected",
    "token": "expected",
    "SLA": "sla_ms",
}

_MAX_DEFINITION_LABEL = 200


class SoapUiParseError(ValueError):
    """Raised when a SoapUI upload cannot be read.

    Attributes:
        code: The import taxonomy code the pipeline reports.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# The parsed document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SoapUiAuth:
    """A saved request's auth declaration — its type only, never a credential.

    Attributes:
        type: The SoapUI ``authType`` as written (``Basic``, ``NTLM``, ``OAuth 2.0`` …), or
            ``WS-Security`` when only a ``wssType`` is set.
        scheme: The canonical scheme identifier (see :data:`AUTH_SCHEMES`).
        ws_security: The WS-Security password type (``PasswordText`` / ``PasswordDigest``), when set.
    """

    type: str
    scheme: str
    ws_security: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag, leaving unset facts out."""
        record: Dict[str, Any] = {"type": self.type, "scheme": self.scheme}
        if self.ws_security:
            record["ws_security"] = self.ws_security
        return record


@dataclass(frozen=True)
class SoapUiRequest:
    """The facts about one REST saved request that the inferred-spec engine has no slot for.

    The field names are the ones :func:`app.client_collection.annotate_operations` reads.

    Attributes:
        name: The request's name.
        method: The upper-cased HTTP method.
        url: The URL handed to the engine.
        folder: ``(interface name,)`` — the interface becomes the operation's tag.
        auth: The request's auth declaration, or ``None``.
        content_type: The request's media type, when it has a body.
    """

    name: str
    method: str
    url: str
    folder: Tuple[str, ...]
    auth: Optional[SoapUiAuth]
    content_type: Optional[str]


@dataclass(frozen=True)
class SoapUiCall:
    """One saved SOAP request (``call``) — its name and auth type; the envelope is not kept."""

    name: str
    auth: Optional[SoapUiAuth]

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag."""
        record: Dict[str, Any] = {"name": self.name}
        if self.auth is not None:
            record["auth"] = self.auth.as_dict()
        return record


@dataclass(frozen=True)
class SoapUiOperation:
    """One binding operation a WSDL interface declares.

    Attributes:
        name: The operation name.
        action: Its ``soapAction``, when stated.
        one_way: Whether it is a one-way operation (no response).
        calls: The saved requests (``call`` elements) kept for it.
    """

    name: str
    action: Optional[str]
    one_way: bool
    calls: Tuple[SoapUiCall, ...] = ()


@dataclass(frozen=True)
class SoapUiWsdlInterface:
    """A WSDL-backed interface and the WSDL located for it.

    Attributes:
        name: The interface name (SoapUI names it after the binding).
        binding: The binding's qualified name (``{ns}Binding``), when stated.
        soap_version: ``1_1`` or ``1_2``, when stated.
        definition: Where the project says the WSDL lives (scrubbed; a label, not a fetch target).
        wsdl_source: ``cache`` (the project's ``definitionCache``), ``fileset`` (an uploaded member)
            or ``not-fetched`` (a remote WSDL the project only links to).
        wsdl_key: Identifies the located WSDL, so two interfaces over one WSDL delegate once.
        wsdl: The WSDL as parsed by the WSDL adapter's reader, or ``None`` when not fetched.
        operations: The binding operations the project declares.
        endpoints: The interface's endpoint URLs (scrubbed).
    """

    name: str
    binding: Optional[str]
    soap_version: Optional[str]
    definition: Optional[str]
    wsdl_source: str
    wsdl_key: Optional[str]
    wsdl: Optional[WsdlDocument]
    operations: Tuple[SoapUiOperation, ...]
    endpoints: Tuple[str, ...]


@dataclass(frozen=True)
class SoapUiProperty:
    """A project property — its *name*, never its value.

    Attributes:
        name: The property name.
        secret: Whether the name says the value is a credential (its value is then never used).
    """

    name: str
    secret: bool

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag."""
        return {"name": self.name, "secret": self.secret}


@dataclass(frozen=True)
class SoapUiStep:
    """One test step, as declared test intent.

    Attributes:
        name: The step's name.
        type: The SoapUI step type (``restrequest``, ``request``, ``transfer``, ``groovy`` …).
        disabled: Whether the step is disabled.
        rest_target: ``(service, resource path, method name)`` for a REST request step.
        soap_target: ``(interface, operation)`` for a SOAP request step.
        assertions: ``{type, name, expects?}`` per assertion (expectations scrubbed).
    """

    name: str
    type: str
    disabled: bool = False
    rest_target: Optional[Tuple[str, str, str]] = None
    soap_target: Optional[Tuple[str, str]] = None
    assertions: Tuple[Dict[str, Any], ...] = ()


@dataclass
class SoapUiDocument:
    """A parsed SoapUI project, ready for :mod:`app.soapui_normalizer`.

    Attributes:
        title: The project's name.
        soapui_version: The ``soapui-version`` the project was saved by, when stated.
        observations: One concrete sample per REST saved request (or bare method) and mock response.
        requests: Per-request facts for the REST observations, in project order.
        rest_targets: ``(interface, resource path, method name)`` → ``(HTTP method, engine URL)``,
            so a test step can be linked to the operation it calls.
        rest_interfaces: The REST interfaces' names, in project order.
        wsdl_interfaces: The WSDL-backed interfaces, in project order.
        server_variables: Leading ``${property}`` endpoint → its default (``None`` when nothing
            defines it or the property is secret).
        endpoints: ``(interface, endpoint URL)`` for every literal interface endpoint.
        environments: ``(environment, service, endpoint URL)`` for every environment endpoint.
        properties: The project's properties, by name.
        test_suites: ``{name, run_type, cases: [{name, disabled, properties, steps}]}`` per suite.
        mock_services: ``{name, kind, actions, responses}`` per mock service.
        limits: Construct id → the locations a declared limit applies to.
        source_label: The filename or paste label.
    """

    title: str
    soapui_version: Optional[str] = None
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[SoapUiRequest] = field(default_factory=list)
    rest_targets: Dict[Tuple[str, str, str], Tuple[str, str]] = field(default_factory=dict)
    rest_interfaces: List[str] = field(default_factory=list)
    wsdl_interfaces: List[SoapUiWsdlInterface] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    endpoints: List[Tuple[str, str]] = field(default_factory=list)
    environments: List[Tuple[str, str, str]] = field(default_factory=list)
    properties: List[SoapUiProperty] = field(default_factory=list)
    test_suites: List[Dict[str, Any]] = field(default_factory=list)
    mock_services: List[Dict[str, Any]] = field(default_factory=list)
    limits: Dict[str, List[str]] = field(default_factory=dict)
    source_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Detection and loading
# ---------------------------------------------------------------------------


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def is_soapui_project(text: Optional[str]) -> bool:
    """Whether ``text`` presents as a SoapUI / ReadyAPI project, without parsing it.

    The root element must be ``soapui-project`` and the SoapUI config namespace must be declared;
    only the head is read, so a truncated or malformed project is still recognised.

    Args:
        text: The candidate document.

    Returns:
        ``True`` for a SoapUI project.
    """
    if not text or root_element_name(text) != _ROOT:
        return False
    return SOAPUI_NAMESPACE in text[:65536]


def _load(text: str, label: Optional[str]) -> ET.Element:
    """Parse a project through the hardened XML reader and check its root.

    Raises:
        SoapUiParseError: With the taxonomy code for the fault.
    """
    try:
        root = read_device_model_xml(text, source_label=label, kind="SoapUI project")
    except DeviceModelXmlError as exc:
        raise SoapUiParseError(str(exc), code=exc.code) from exc
    if local_name(root.tag) == _ROOT and root.tag.startswith("{" + SOAPUI_NAMESPACE + "}"):
        return root
    if is_wsdl(text):
        other = "a WSDL document"
    elif local_name(root.tag) == "application":
        other = "a WADL document"
    else:
        other = f"an XML document with a `{local_name(root.tag)}` root"
    raise SoapUiParseError(
        f"The upload{_where(label)} is {other}, not a SoapUI project: expected a `soapui-project` root "
        f"in the {SOAPUI_NAMESPACE} namespace",
        code="FORMAT_MISMATCH",
    )


# ---------------------------------------------------------------------------
# Values, properties and expansions
# ---------------------------------------------------------------------------


def _scrub_named(name: str, value: str) -> str:
    """Scrub a parameter / header value; a whole ``${expansion}`` is a reference and is kept."""
    return scrub_named(name, value, reference=_WHOLE_EXPANSION_RE)


def _expansion_name(inner: str) -> Tuple[str, str]:
    """Split the inside of ``${…}`` into ``(scope, name)``.

    ``#Project#baseUrl`` → ``("project", "baseUrl")``; ``Step#prop`` → ``("step", "prop")``;
    ``baseUrl`` → ``("", "baseUrl")``; a Groovy ``=expression`` → ``("expression", "expression")``.
    """
    inner = inner.strip()
    if inner.startswith("="):
        return "expression", "expression"
    if inner.startswith("#"):
        _, _, rest = inner.partition("#")
        scope, _, name = rest.partition("#")
        return scope.strip().lower(), name.strip() or scope.strip()
    if "#" in inner:
        _, _, name = inner.rpartition("#")
        return "step", name.strip()
    return "", inner


def _identifier(name: str) -> str:
    """A property name as a server / path variable name (``{baseUrl}``)."""
    cleaned = _NAME_CHARS_RE.sub("_", name).strip("_")
    return cleaned or "variable"


@dataclass
class _Properties:
    """The project's properties: values for resolving expansions, secret ones withheld."""

    values: Dict[str, str] = field(default_factory=dict)
    secret: set = field(default_factory=set)

    def default_for(self, scope: str, name: str) -> Optional[str]:
        """The scrubbed value a ``${#Project#name}`` expansion resolves to, or ``None``.

        A secret-named property, a property of another scope, a value that is itself an expansion,
        or an empty value resolves to nothing.
        """
        if scope not in _PROJECT_SCOPES or name in self.secret:
            return None
        value = (self.values.get(name) or "").strip()
        if not value or _EXPANSION_RE.search(value):
            return None
        return scrub_value(value)


def _read_properties(element: Optional[ET.Element]) -> Tuple[_Properties, List[SoapUiProperty]]:
    """Read a ``properties`` block into the expansion table and the name-only records."""
    table = _Properties()
    records: List[SoapUiProperty] = []
    for prop in children(element, "property"):
        name = child_text(prop, "name")
        if not name:
            continue
        secret = bool(SECRET_NAME_RE.search(name))
        records.append(SoapUiProperty(name=name, secret=secret))
        if secret:
            table.secret.add(name)
        value_el = child(prop, "value")
        table.values.setdefault(name, (value_el.text or "") if value_el is not None else "")
    return table, records


def _property_names(element: Optional[ET.Element]) -> List[str]:
    """The names of a test case's / suite's properties (values are never kept)."""
    return sorted({name for prop in children(element, "property") if (name := child_text(prop, "name"))})


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _read_auth(element: Optional[ET.Element]) -> Optional[SoapUiAuth]:
    """Read a ``credentials`` block — ``authType`` and ``wssType`` only, never a credential."""
    credentials = child(element, "credentials")
    if credentials is None:
        return None
    auth_type = child_text(credentials, "authType") or ""
    wss_type = child_text(credentials, "wssType")
    scheme = AUTH_SCHEMES.get(auth_type.lower())
    if scheme is not None:
        return SoapUiAuth(type=auth_type, scheme=scheme, ws_security=wss_type)
    if wss_type:
        return SoapUiAuth(type="WS-Security", scheme="authorization", ws_security=wss_type)
    return None


# ---------------------------------------------------------------------------
# REST interfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Parameter:
    name: str
    style: str
    value: str


def _read_parameters(element: Optional[ET.Element]) -> List[_Parameter]:
    """Read a resource's or method's ``parameters`` definitions."""
    parameters: List[_Parameter] = []
    for param in children(element, "parameter"):
        name = child_text(param, "name")
        if not name:
            continue
        value_el = child(param, "value")
        parameters.append(
            _Parameter(
                name=name,
                style=(child_text(param, "style") or _QUERY).upper(),
                value=(value_el.text or "").strip() if value_el is not None else "",
            )
        )
    return parameters


def _entries(element: Optional[ET.Element]) -> Dict[str, str]:
    """A saved request's ``parameters`` values — ``<entry key=… value=…/>`` pairs."""
    return {
        str(entry.get("key")): str(entry.get("value") or "")
        for entry in children(child(element, "parameters"), "entry")
        if entry.get("key")
    }


def _saved_headers(element: ET.Element) -> List[Tuple[str, str]]:
    """The headers a saved request keeps in its ``…@request-headers`` setting.

    SoapUI stores them as an escaped ``<xml-fragment>`` of ``<con:entry key value/>`` elements
    inside the setting's text; a fragment that does not parse contributes nothing.
    """
    headers: List[Tuple[str, str]] = []
    for setting in children(child(element, "settings"), "setting"):
        if not str(setting.get("id") or "").endswith("@request-headers") or not (setting.text or "").strip():
            continue
        try:
            fragment = parse_xml(setting.text)
        except SecureXmlError:
            continue
        for entry in fragment.iter():
            if isinstance(entry.tag, str) and local_name(entry.tag) == "entry" and entry.get("key"):
                headers.append((str(entry.get("key")), str(entry.get("value") or "")))
    return headers


def _join_path(*parts: str) -> str:
    """Join path pieces with single slashes into a path-absolute path (``/v2/orders/{id}``)."""
    segments = [segment for part in parts for segment in (part or "").split("/") if segment]
    return "/" + "/".join(segments)


def _template_path(path: str) -> str:
    """Turn ``${…}`` expansions inside a path into ``{name}`` path parameters."""
    return _EXPANSION_RE.sub(lambda match: "{" + _identifier(_expansion_name(match.group(1))[1]) + "}", path)


def _json_body(raw: str) -> str:
    """Scrub a JSON body, quoting bare ``${expansions}`` when that is what keeps it parseable."""
    scrubbed = scrub_value(raw)
    try:
        json.loads(scrubbed)
    except json.JSONDecodeError:
        quoted = _BARE_JSON_EXPANSION_RE.sub(lambda match: json.dumps(match.group(1)), scrubbed)
        try:
            json.loads(quoted)
        except json.JSONDecodeError:
            return scrubbed
        return quoted
    return scrubbed


def _definition_label(definition: str) -> str:
    """A ``definition`` attribute as a label: scrubbed, userinfo dropped, bounded in length."""
    text = scrub_value(definition.strip())
    if "://" in text:
        parts = urlsplit(text)
        text = text.replace(parts.netloc, parts.netloc.rsplit("@", 1)[-1], 1)
    return text[:_MAX_DEFINITION_LABEL]


@dataclass
class _Reader:
    """Reads one project into a :class:`SoapUiDocument`."""

    document: SoapUiDocument
    properties: _Properties
    members: Mapping[str, str]
    member_label: Dict[str, str] = field(default_factory=dict)

    # -- limits -------------------------------------------------------------

    def limit(self, construct: str, location: str) -> None:
        """Record that a declared limit applies at ``location``."""
        self.document.limits.setdefault(construct, []).append(location)

    # -- endpoints ----------------------------------------------------------

    def endpoint_base(self, endpoint: Optional[str]) -> str:
        """The URL prefix an endpoint contributes to an engine URL.

        A literal endpoint keeps its scheme and host (userinfo dropped — it is a credential) and
        its path; an endpoint that starts with a ``${property}`` becomes a server template, so the
        engine URL is path-absolute and the property is a server variable. No endpoint is ``""``.
        """
        text = (endpoint or "").strip()
        if not text:
            return ""
        leading = _EXPANSION_RE.match(text)
        if leading:
            scope, name = _expansion_name(leading.group(1))
            variable = _identifier(name)
            self.document.server_variables.setdefault(variable, None)
            if self.document.server_variables[variable] is None:
                self.document.server_variables[variable] = self.properties.default_for(scope, name)
            return _template_path(text[leading.end() :].rstrip("/"))
        parts = urlsplit(text if "://" in text else f"https://{text}")
        host = parts.netloc.rsplit("@", 1)[-1]
        return f"{parts.scheme or 'https'}://{host}{_template_path(parts.path.rstrip('/'))}"

    def literal_endpoint(self, endpoint: str) -> Optional[str]:
        """An interface / environment endpoint as a server URL, or ``None`` for an expansion."""
        text = endpoint.strip()
        if not text or _EXPANSION_RE.match(text):
            return None
        return scrub_value(self.endpoint_base(text))

    # -- REST ---------------------------------------------------------------

    def read_rest_interface(self, interface: ET.Element, name: str) -> int:
        """Read a REST interface's resources and methods; returns the number of methods read."""
        base_path = interface.get("basePath") or ""
        endpoints = [
            text for el in children(child(interface, "endpoints"), "endpoint") if (text := (el.text or "").strip())
        ]
        for endpoint in endpoints:
            literal = self.literal_endpoint(endpoint)
            if literal:
                self.document.endpoints.append((name, literal))
        self.document.rest_interfaces.append(name)
        count = 0
        for resource in children(interface, "resource"):
            count += self.read_resource(
                resource, interface=name, base_path=base_path, parent="", inherited=[], endpoints=endpoints
            )
        return count

    def read_resource(
        self,
        resource: ET.Element,
        *,
        interface: str,
        base_path: str,
        parent: str,
        inherited: List[_Parameter],
        endpoints: Sequence[str],
    ) -> int:
        """Read one resource, its methods and its child resources (paths and parameters inherit)."""
        resource_path = _join_path(parent, resource.get("path") or "")
        parameters = inherited + _read_parameters(child(resource, "parameters"))
        count = 0
        for method in children(resource, "method"):
            self.read_method(
                method,
                interface=interface,
                base_path=base_path,
                resource_path=resource_path,
                inherited=parameters,
                endpoints=endpoints,
            )
            count += 1
        for sub in children(resource, "resource"):
            count += self.read_resource(
                sub,
                interface=interface,
                base_path=base_path,
                parent=resource_path,
                inherited=parameters,
                endpoints=endpoints,
            )
        return count

    def read_method(
        self,
        method: ET.Element,
        *,
        interface: str,
        base_path: str,
        resource_path: str,
        inherited: List[_Parameter],
        endpoints: Sequence[str],
    ) -> None:
        """Read one method's saved requests (or the method alone) into observations."""
        verb = (method.get("method") or "").strip().upper()
        method_name = method.get("name") or f"{verb} {resource_path}"
        if not verb:
            raise SoapUiParseError(
                f"REST method {method_name!r} of interface {interface!r} has no HTTP `method`", code="INPUT_MALFORMED"
            )
        parameters = inherited + _read_parameters(child(method, "parameters"))
        for param in parameters:
            if param.style == _MATRIX:
                self.limit("soapui.matrix_parameter", f"{interface} {verb} {resource_path} ;{param.name}")
        request_media: Optional[str] = None
        response_status: Optional[int] = None
        for representation in children(method, "representation"):
            kind = (representation.get("type") or "").upper()
            media = child_text(representation, "mediaType")
            if kind == "REQUEST" and media and request_media is None:
                request_media = media
            status = child_text(representation, "status")
            if kind == "RESPONSE" and status and response_status is None:
                codes = [int(code) for code in status.split() if code.isdigit()]
                response_status = next((code for code in codes if 200 <= code < 300), codes[0] if codes else None)

        saved = children(method, "request")
        path = _join_path(base_path, resource_path)
        first_url: Optional[str] = None
        for index, request in enumerate(saved or [None]):
            label = request.get("name") if request is not None else None
            endpoint = child_text(request, "endpoint") if request is not None else None
            base = self.endpoint_base(endpoint or (endpoints[0] if endpoints else None))
            url = base + _template_path(path)
            values = _entries(request) if request is not None else {}
            query: List[Tuple[str, str]] = []
            headers: Dict[str, Tuple[str, str]] = {}
            for param in parameters:
                value = values.get(param.name, param.value)
                if param.style == _QUERY:
                    query.append((param.name, _scrub_named(param.name, value)))
                elif param.style == _HEADER:
                    headers[param.name.lower()] = (param.name, _scrub_named(param.name, value))
            if request is not None:
                for key, value in _saved_headers(request):
                    headers[key.lower()] = (key, _scrub_named(key, value))
            body: Optional[str] = None
            content_type: Optional[str] = None
            if request is not None:
                body_el = child(request, "request")
                raw = (body_el.text or "") if body_el is not None else ""
                if raw.strip():
                    content_type = request.get("mediaType") or request_media or "application/json"
                    body = _json_body(raw) if "json" in content_type else scrub_value(raw)
                    headers.setdefault("content-type", ("Content-Type", content_type))
            name = label or method_name
            self.document.observations.append(
                HttpObservation(
                    method=verb,
                    url=url,
                    headers=tuple(headers[key] for key in sorted(headers)),
                    query=tuple(query),
                    request_body=body,
                    response_status=response_status,
                    source_location=f"{interface}{resource_path}#{method_name}"
                    + (f"/{index}" if len(saved) > 1 else ""),
                    source_label=name,
                    source_file=self.document.source_label,
                )
            )
            auth = _read_auth(request) if request is not None else None
            if auth is not None:
                self.limit("soapui.auth_credential", f"{interface} {method_name} / {name}")
            self.document.requests.append(
                SoapUiRequest(
                    name=name,
                    method=verb,
                    url=url,
                    folder=(interface,),
                    auth=auth,
                    content_type=content_type,
                )
            )
            first_url = first_url or url
        self.document.rest_targets[(interface, resource_path, method_name)] = (verb, first_url or path)

    # -- WSDL ---------------------------------------------------------------

    def locate_wsdl(
        self, interface: ET.Element, name: str
    ) -> Tuple[str, Optional[str], Optional[str], Mapping[str, str]]:
        """Find the WSDL a WSDL interface names.

        Looks in the project's ``definitionCache`` first (SoapUI keeps a copy of each WSDL and XSD
        part there), then among the uploaded fileset members (by the ``definition`` path or its file
        name, then the cache's ``rootPart`` file name).

        Returns:
            ``(source, key, text, members)`` — ``source`` is ``cache``, ``fileset`` or
            ``not-fetched``; ``text`` is ``None`` when not fetched; ``members`` are the documents
            the WSDL's schema imports resolve against.

        Raises:
            SoapUiParseError: ``INPUT_REFERENCE_UNRESOLVED`` when the definition is a local file
                that is neither cached nor uploaded.
        """
        definition = (interface.get("definition") or "").strip()
        cache = child(interface, "definitionCache")
        parts: Dict[str, str] = {}
        for part in children(cache, "part"):
            url = child_text(part, "url")
            content = child(part, "content")
            if url and content is not None and (content.text or "").strip():
                parts[url] = content.text or ""
        root_part = (cache.get("rootPart") if cache is not None else None) or definition
        if parts:
            root_url = root_part if root_part in parts else definition if definition in parts else next(iter(parts))
            return "cache", f"cache:{root_url}", parts[root_url], parts

        for candidate in (definition, root_part):
            member = _member_for(candidate, self.members)
            if member is not None:
                return "fileset", f"member:{member}", self.members[member], self.members
        if re.match(r"^https?://", definition, re.IGNORECASE):
            return "not-fetched", None, None, {}
        raise SoapUiParseError(
            f"Interface {name!r} takes its WSDL from `{_definition_label(definition) or '(no definition)'}`, which "
            "is neither cached in the project nor among the uploaded files — upload the WSDL beside the project",
            code="INPUT_REFERENCE_UNRESOLVED",
        )

    def read_wsdl_interface(self, interface: ET.Element, name: str) -> int:
        """Read a WSDL interface; returns the number of operations it declares."""
        source, key, text, members = self.locate_wsdl(interface, name)
        wsdl: Optional[WsdlDocument] = None
        if text is not None:
            label = key.split(":", 1)[1] if key else name
            try:
                wsdl = parse_wsdl(text, source_label=label, members=members)
            except (WsdlParseError, SecureXmlError) as exc:
                raise SoapUiParseError(
                    f"The WSDL behind interface {name!r} ({label}) cannot be read: {exc}",
                    code=getattr(exc, "code", None) or "INPUT_MALFORMED",
                ) from exc
        operations: List[SoapUiOperation] = []
        for operation in children(interface, "operation"):
            op_name = operation.get("name") or operation.get("bindingOperationName")
            if not op_name:
                continue
            calls: List[SoapUiCall] = []
            for call in children(operation, "call"):
                call_name = call.get("name") or f"{op_name} request"
                auth = _read_auth(call)
                if auth is not None:
                    self.limit("soapui.auth_credential", f"{name} {op_name} / {call_name}")
                calls.append(SoapUiCall(name=call_name, auth=auth))
                self.limit("soapui.saved_envelope", f"{name} {op_name} / {call_name}")
            one_way = operation.get("isOneWay") == "true" or (operation.get("type") or "").lower() == "one-way"
            operations.append(
                SoapUiOperation(
                    name=op_name, action=operation.get("action") or None, one_way=one_way, calls=tuple(calls)
                )
            )
        if wsdl is None:
            for operation in operations:
                self.limit("soapui.wsdl_not_fetched", f"{name} {operation.name}")
        endpoints: List[str] = []
        for el in children(child(interface, "endpoints"), "endpoint"):
            literal = self.literal_endpoint(el.text or "")
            if literal:
                endpoints.append(literal)
                self.document.endpoints.append((name, literal))
        self.document.wsdl_interfaces.append(
            SoapUiWsdlInterface(
                name=name,
                binding=interface.get("bindingName") or None,
                soap_version=interface.get("soapVersion") or None,
                definition=_definition_label(interface.get("definition") or "") or None,
                wsdl_source=source,
                wsdl_key=key,
                wsdl=wsdl,
                operations=tuple(operations),
                endpoints=tuple(endpoints),
            )
        )
        declared = len(operations)
        if wsdl is not None:
            declared += sum(len(port_type.operations) for port_type in wsdl.port_types)
        return declared

    # -- mock services ------------------------------------------------------

    def read_mock_services(self, project: ET.Element) -> int:
        """Read REST mock responses as response observations; SOAP mock services by name only."""
        observed = 0
        for mock in children(project, "restMockService"):
            mock_name = mock.get("name") or "REST mock service"
            actions = children(mock, "restMockAction")
            responses = 0
            for action in actions:
                verb = (action.get("method") or "GET").strip().upper()
                path = _template_path(_join_path(action.get("resourcePath") or ""))
                matched = self.match_request(verb, path)
                for response in children(action, "response"):
                    status_text = (response.get("httpResponseStatus") or "").strip()
                    content = child(response, "responseContent")
                    body = (content.text or "") if content is not None else ""
                    self.document.observations.append(
                        HttpObservation(
                            method=verb,
                            url=matched.url if matched else path,
                            headers=matched.headers if matched else (),
                            query=matched.query if matched else (),
                            response_status=int(status_text) if status_text.isdigit() else None,
                            response_body=_json_body(body) if body.strip() else None,
                            source_location=f"{mock_name}#{action.get('name') or path}/{response.get('name') or ''}",
                            source_label=response.get("name") or mock_name,
                            source_file=self.document.source_label,
                        )
                    )
                    responses += 1
                    observed += 1
                if child_text(action, "dispatchStyle") or child_text(action, "dispatchPath"):
                    self.limit("soapui.mock_dispatch", f"{mock_name} {action.get('name') or path}")
            self.document.mock_services.append(
                {"name": mock_name, "kind": "rest", "actions": len(actions), "responses": responses}
            )
        for mock in children(project, "mockService"):
            mock_name = mock.get("name") or "SOAP mock service"
            operations = children(mock, "mockOperation")
            responses = sum(len(children(operation, "response")) for operation in operations)
            self.document.mock_services.append(
                {"name": mock_name, "kind": "soap", "actions": len(operations), "responses": responses}
            )
            self.limit("soapui.soap_mock_service", mock_name)
        return observed

    def match_request(self, verb: str, path: str) -> Optional[HttpObservation]:
        """The first REST request observation a mock action answers — same verb, same path shape."""
        for observation in self.document.observations:
            if observation.method != verb or observation.response_body is not None:
                continue
            observed = urlsplit(observation.url).path if "://" in observation.url else observation.url
            if _path_matches(observed, path):
                return observation
        return None

    # -- tests --------------------------------------------------------------

    def read_test_suites(self, project: ET.Element) -> None:
        """Read every test suite as declared test intent."""
        for suite in children(project, "testSuite"):
            suite_name = suite.get("name") or "Test suite"
            cases: List[Dict[str, Any]] = []
            for case in children(suite, "testCase"):
                case_name = case.get("name") or "Test case"
                where = f"{suite_name} / {case_name}"
                steps = [self.read_step(step, where) for step in children(case, "testStep")]
                cases.append(
                    {
                        "name": case_name,
                        "disabled": case.get("disabled") == "true",
                        "properties": _property_names(child(case, "properties")),
                        "steps": steps,
                    }
                )
                self.limit("soapui.test_case", where)
            self.document.test_suites.append(
                {
                    "name": suite_name,
                    "run_type": child_text(suite, "runType"),
                    "disabled": suite.get("disabled") == "true",
                    "properties": _property_names(child(suite, "properties")),
                    "cases": cases,
                }
            )

    def read_step(self, step: ET.Element, where: str) -> SoapUiStep:
        """Read one test step: its type, target and assertions (scripts are never read)."""
        step_type = (step.get("type") or "").strip()
        name = step.get("name") or step_type or "step"
        config = child(step, "config")
        rest_target = soap_target = None
        request: Optional[ET.Element] = None
        if step_type.lower() in _REST_STEP_TYPES and config is not None:
            rest_target = (
                config.get("service") or "",
                _join_path(config.get("resourcePath") or ""),
                config.get("methodName") or "",
            )
            request = child(config, "restRequest")
        elif step_type.lower() in _SOAP_STEP_TYPES and config is not None:
            soap_target = (child_text(config, "interface") or "", child_text(config, "operation") or "")
            request = child(config, "request")
        elif step_type.lower() == "httprequest" and config is not None:
            request = child(config, "restRequest")
        if step_type.lower() == "groovy":
            self.limit("soapui.groovy_script", f"{where} / {name}")
        if request is not None and _read_auth(request) is not None:
            self.limit("soapui.auth_credential", f"{where} / {name}")
        assertions: List[Dict[str, Any]] = []
        for assertion in children(request, "assertion"):
            kind = assertion.get("type") or "assertion"
            record: Dict[str, Any] = {"type": kind, "name": assertion.get("name") or kind}
            expects: Dict[str, str] = {}
            for element in child(assertion, "configuration") or []:
                if not isinstance(element.tag, str):
                    continue
                key = _ASSERTION_FACTS.get(local_name(element.tag))
                text = (element.text or "").strip()
                if key and text:
                    expects[key] = scrub_value(" ".join(text.split()))
            if expects:
                record["expects"] = dict(sorted(expects.items()))
            if "script" in kind.lower():
                self.limit("soapui.groovy_script", f"{where} / {name} / {record['name']}")
            assertions.append(record)
        return SoapUiStep(
            name=name,
            type=step_type,
            disabled=step.get("disabled") == "true",
            rest_target=rest_target,
            soap_target=soap_target,
            assertions=tuple(assertions),
        )


def _path_matches(observed: str, mock: str) -> bool:
    """Whether a mock action's path answers a request path.

    Segments must agree one for one; a ``{param}`` segment on either side matches any segment, so
    ``/v2/orders/ORD-1`` answers ``/v2/orders/{orderId}``.
    """
    left = [segment for segment in observed.split("/") if segment]
    right = [segment for segment in mock.split("/") if segment]
    if len(left) != len(right):
        return False
    return all(a == b or a.startswith("{") or b.startswith("{") for a, b in zip(left, right))


def _member_for(location: str, members: Mapping[str, str]) -> Optional[str]:
    """The fileset member a ``definition`` / ``rootPart`` names — by path, then by file name."""
    location = (location or "").strip()
    if not location or not members:
        return None
    if location in members:
        return location
    if re.match(r"^https?://", location, re.IGNORECASE):
        return None
    tail = re.split(r"[\\/]", location)[-1]
    if not tail:
        return None
    for path in sorted(members):
        if path == tail or path.rsplit("/", 1)[-1] == tail:
            return path
    return None


def _interface_kind(interface: ET.Element) -> str:
    """``rest``, ``wsdl``, or the (unsupported) kind an interface declares.

    The ``xsi:type`` (``con:RestService`` / ``con:WsdlInterface``) is authoritative; the plain
    ``type`` attribute (``rest`` / ``wsdl``) is the fallback for a project that omits it.
    """
    declared = next(
        (
            value.rsplit(":", 1)[-1]
            for key, value in interface.attrib.items()
            if key.startswith("{") and local_name(key) == "type"
        ),
        "",
    )
    kinds = {"restservice": "rest", "wsdlinterface": "wsdl"}
    if declared:
        return kinds.get(declared.lower(), declared)
    return (interface.get("type") or "unknown").lower()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _build(root: ET.Element, *, members: Mapping[str, str], source_label: Optional[str]) -> SoapUiDocument:
    """Read a parsed project root into a :class:`SoapUiDocument`.

    Raises:
        SoapUiParseError: With the taxonomy code for the fault.
    """
    title = (root.get("name") or "").strip() or "SoapUI project"
    properties, records = _read_properties(child(root, "properties"))
    document = SoapUiDocument(
        title=title,
        soapui_version=root.get("soapui-version") or None,
        properties=records,
        source_label=source_label,
    )
    reader = _Reader(document=document, properties=properties, members=members)
    for prop in records:
        if prop.secret:
            reader.limit("soapui.secret_property", prop.name)

    interfaces = children(root, "interface")
    has_mocks = bool(children(root, "restMockService") or children(root, "mockService"))
    if not interfaces and not has_mocks:
        raise SoapUiParseError(
            f"The project {title!r} has no interfaces or mock services — nothing in it describes an API",
            code="INPUT_SEMANTIC_INVALID",
        )
    operations = 0
    for index, interface in enumerate(interfaces):
        name = (interface.get("name") or "").strip() or f"Interface {index + 1}"
        kind = _interface_kind(interface)
        if kind == "rest":
            operations += reader.read_rest_interface(interface, name)
        elif kind == "wsdl":
            operations += reader.read_wsdl_interface(interface, name)
        else:
            reader.limit("soapui.unsupported_interface", f"{name} ({kind})")
    operations += reader.read_mock_services(root)
    if operations == 0:
        raise SoapUiParseError(
            f"The interfaces of project {title!r} declare no operations — there is nothing to import",
            code="INPUT_SEMANTIC_INVALID",
        )

    for environment in children(child(root, "environments"), "environment"):
        env_name = environment.get("name") or "Environment"
        for service in children(child(environment, "services"), "service"):
            for endpoint in children(service, "endpoint"):
                literal = reader.literal_endpoint(endpoint.text or "")
                if literal:
                    document.environments.append((env_name, service.get("name") or "", literal))
    reader.read_test_suites(root)
    return document


def parse_soapui_text(
    raw: str,
    *,
    source_label: Optional[str] = None,
    members: Optional[Mapping[str, str]] = None,
) -> SoapUiDocument:
    """Parse one SoapUI / ReadyAPI project.

    Args:
        raw: The decoded project XML.
        source_label: The filename or paste label.
        members: Files uploaded beside the project (a WSDL its interface names), keyed by path.

    Returns:
        The parsed document.

    Raises:
        SoapUiParseError: With the taxonomy code for the fault.
    """
    root = _load(raw, source_label)
    return _build(root, members=members or {}, source_label=source_label)


def parse_soapui_fileset(
    members: Mapping[str, str],
    *,
    root: Optional[str] = None,
    source_label: Optional[str] = None,
) -> SoapUiDocument:
    """Parse a project uploaded together with the WSDL / XSD files its interfaces name.

    The root member is the project; when no root is named, the first member that presents as a
    SoapUI project is. Every other member is available to the project's WSDL interfaces.

    Args:
        members: Member text keyed by path.
        root: The project member's path.
        source_label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        SoapUiParseError: ``FORMAT_MISMATCH`` when no member is a SoapUI project, otherwise the
            project's own taxonomy code.
    """
    project = root if root in members and is_soapui_project(members[root]) else None
    if project is None:
        project = next((path for path in sorted(members) if is_soapui_project(members[path])), None)
    if project is None:
        if root in members:
            return parse_soapui_text(members[root], source_label=root, members=members)
        raise SoapUiParseError("The upload has no SoapUI project in it", code="FORMAT_MISMATCH")
    others = {path: text for path, text in members.items() if path != project}
    return parse_soapui_text(members[project], source_label=source_label or project, members=others)
