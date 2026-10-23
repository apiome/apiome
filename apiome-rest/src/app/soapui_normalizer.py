"""SoapUI / ReadyAPI project → canonical model normalizer — FMT-10.3 (#5477).

A project is read by :mod:`app.soapui_parser`; this module assembles **one** canonical model from
its parts, delegating each kind of interface to the machinery that already owns it rather than
re-implementing any of it:

* **WSDL-backed interfaces → the WSDL adapter.** The located WSDL is normalized by
  :class:`app.wsdl_normalizer.WsdlNormalizer`, so its services, operations and XSD types are
  byte-for-byte what importing the WSDL on its own produces (the WSDL corpus goldens). Two
  interfaces over one WSDL (a SOAP 1.1 and a 1.2 binding) delegate once. A WSDL the project only
  links to is never fetched: its operations are declared from the project — name, kind (one-way or
  request-response) and SOAP action — with no message schemas, and the gap is a declared limit.
* **REST interfaces → the shared inferred-spec engine** (:mod:`app.inferred_spec`), exactly as for
  the Hoppscotch and Thunder Client collections: saved requests and mock responses are
  observations; :func:`app.client_collection.annotate_operations` then adds what the engine has no
  slot for — the interface as the operation's tag, the request's auth scheme, its media type.
* **Test suites → declared test intent** (:mod:`app.declared_test_intent`): every request step is
  linked to the canonical operation it calls.
* **Endpoints and environments → servers**; a ``${#Project#baseUrl}`` endpoint becomes a
  ``{baseUrl}`` server whose default is the project property's value (never a secret one's).
* **Declared limits** (scripts, withheld credentials, unfetched WSDLs, mock dispatch …) ride in
  ``extras["soapui"]["capability_limits"]`` for the coverage ledger.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

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
from .client_collection import annotate_operations, declared_limit, template_servers
from .declared_test_intent import DECLARED_TESTS_EXTRAS_KEY, build_declared_tests
from .inferred_spec import infer_canonical_api
from .normalizer import Keys, Normalizer, normalize_ordering
from .soapui_parser import FORMAT_KEY, SoapUiDocument, SoapUiStep, SoapUiWsdlInterface
from .wsdl_normalizer import WsdlNormalizer

__all__ = ["AUTH_EXTRAS_KEY", "LIMIT_NOTES", "PARTIAL_LIMITS", "SOAPUI_EXTRAS_KEY", "SoapUiNormalizer"]

#: The root extras key holding the SoapUI projection record.
SOAPUI_EXTRAS_KEY = "soapui"

#: The REST operation extras key holding each saved request's auth declaration (type only).
AUTH_EXTRAS_KEY = "soapui_auth"

#: What the import does with each declared limit, by construct id.
LIMIT_NOTES: Dict[str, str] = {
    "soapui.test_case": "Test cases are kept as declared test intent (`extras.declared_tests`): steps, the "
    "operations they call and their assertion kinds. They are not run.",
    "soapui.groovy_script": "Groovy scripts (script steps and script assertions) are never read; the step or "
    "assertion is kept by name.",
    "soapui.auth_credential": "The auth type (and WS-Security password type) is kept; usernames, passwords and "
    "domains are never read.",
    "soapui.secret_property": "A property whose name says it holds a credential is listed by name; its value is "
    "withheld.",
    "soapui.wsdl_not_fetched": "The interface links to a WSDL that is neither cached in the project nor uploaded, "
    "and it is never fetched: the operation is declared by name and SOAP action, without message schemas.",
    "soapui.saved_envelope": "A saved SOAP request is kept by name and auth type; its envelope is not modelled — "
    "the message schema comes from the WSDL.",
    "soapui.matrix_parameter": "Matrix parameters (`;name=value` path segments) are not modelled.",
    "soapui.mock_dispatch": "Mock dispatch rules (sequence, script, query match) are not modelled; the canned "
    "responses become inferred response schemas.",
    "soapui.soap_mock_service": "SOAP mock services are listed by name; their canned envelopes are not modelled.",
    "soapui.unsupported_interface": "Only WSDL and REST interfaces are read; this interface kind is left out.",
}

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a construct left out.
PARTIAL_LIMITS = frozenset(
    {
        "soapui.test_case",
        "soapui.auth_credential",
        "soapui.secret_property",
        "soapui.wsdl_not_fetched",
        "soapui.saved_envelope",
    }
)


def _capability_limits(source: SoapUiDocument) -> List[Dict[str, Any]]:
    """The declared limits the reader met, in the shape the coverage ledger reads."""
    return [
        declared_limit(construct, source.limits[construct], LIMIT_NOTES[construct])
        for construct in sorted(source.limits)
    ]


def _binding_namespace(binding: Optional[str]) -> Optional[str]:
    """The namespace of a ``{namespace}LocalName`` binding name, if it has one."""
    if binding and binding.startswith("{") and "}" in binding:
        return binding[1 : binding.index("}")] or None
    return None


def _declared_service(interface: SoapUiWsdlInterface) -> Service:
    """A WSDL interface whose WSDL was not fetched, declared from the project's operations."""
    service_key = Keys.type(interface.name, _binding_namespace(interface.binding))
    operations = [
        Operation(
            key=Keys.operation_rpc(service_key, operation.name),
            name=operation.name,
            kind=OperationKind.ONE_WAY if operation.one_way else OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            extras={"soap_action": operation.action} if operation.action else {},
        )
        for operation in interface.operations
    ]
    return Service(key=service_key, name=interface.name, operations=operations)


def _interface_record(interface: SoapUiWsdlInterface) -> Dict[str, Any]:
    """The ``extras["soapui"]["interfaces"]`` entry of a WSDL interface."""
    record: Dict[str, Any] = {"name": interface.name, "kind": "wsdl", "wsdl_source": interface.wsdl_source}
    for key, value in (
        ("binding", interface.binding),
        ("soap_version", interface.soap_version),
        ("definition", interface.definition),
    ):
        if value:
            record[key] = value
    record["operations"] = [
        {
            "name": operation.name,
            **({"soap_action": operation.action} if operation.action else {}),
            "one_way": operation.one_way,
            "saved_requests": [call.as_dict() for call in operation.calls],
        }
        for operation in interface.operations
    ]
    return record


def _merge_servers(existing: Iterable[Server], extra: Iterable[Server]) -> List[Server]:
    """Servers with ``extra`` added where no server already has the same URL, sorted by URL."""
    merged: Dict[str, Server] = {}
    for server in list(existing) + list(extra):
        merged.setdefault(server.url.rstrip("/"), server)
    return sorted(merged.values(), key=lambda server: server.url)


class _OperationIndex:
    """Finds the canonical operation a test step calls."""

    def __init__(self, source: SoapUiDocument, api: CanonicalApi, wsdl_services: Dict[str, List[Service]]) -> None:
        self._source = source
        self._by_sample: Dict[Tuple[str, str], str] = {}
        for service in api.services:
            for operation in service.operations:
                evidence = operation.extras.get("inference_evidence") or {}
                for url in evidence.get("sample_urls") or []:
                    self._by_sample.setdefault((operation.http_method or "", url), operation.key)
        self._wsdl_services = wsdl_services

    def rest(self, target: Tuple[str, str, str]) -> Optional[str]:
        """The operation key of a REST step's ``(service, resource path, method name)``."""
        found = self._source.rest_targets.get(target)
        if found is None:
            matches = [
                hit for key, hit in self._source.rest_targets.items() if key[0] == target[0] and key[2] == target[2]
            ]
            found = matches[0] if len(matches) == 1 else None
        return self._by_sample.get(found) if found else None

    def soap(self, target: Tuple[str, str]) -> Optional[str]:
        """The operation key of a SOAP step's ``(interface, operation)``."""
        for service in self._wsdl_services.get(target[0], []):
            for operation in service.operations:
                if operation.name == target[1]:
                    return operation.key
        return None

    def step(self, step: SoapUiStep) -> Dict[str, Any]:
        """One step's declared-test-intent record, linked to its operation."""
        record: Dict[str, Any] = {"name": step.name, "type": step.type}
        if step.disabled:
            record["disabled"] = True
        if step.rest_target is not None:
            service, path, method = step.rest_target
            record["target"] = " ".join(part for part in (service, method or path) if part)
            record["operation"] = self.rest(step.rest_target)
        elif step.soap_target is not None:
            record["target"] = " ".join(part for part in step.soap_target if part)
            record["operation"] = self.soap(step.soap_target)
        if step.assertions:
            record["assertions"] = [dict(assertion) for assertion in step.assertions]
        return record


class SoapUiNormalizer(Normalizer, register=True):
    """Normalize a parsed SoapUI project into one canonical model."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed SoapUI project.

        Args:
            source: A :class:`~app.soapui_parser.SoapUiDocument`.
            include_raw: Whether to keep the engine's observation summary and the WSDL text on ``raw``.

        Returns:
            The canonical model: the REST interfaces' inferred service, each WSDL's services and
            types as the WSDL adapter normalizes them, and every unfetched WSDL interface's
            declared service.

        Raises:
            ValueError: When ``source`` is not a parsed SoapUI project.
        """
        if not isinstance(source, SoapUiDocument):
            raise ValueError("SoapUI source must be a SoapUiDocument (see app.soapui_parser.parse_soapui_text)")

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="soap",
            identity=ApiIdentity(name=source.title),
        )
        raw: Dict[str, Any] = {}
        schemes: set = set()
        if source.observations:
            inferred = infer_canonical_api(
                source.observations, title=source.title, format_key=FORMAT_KEY, include_raw=include_raw
            )
            api = inferred.api
            schemes = annotate_operations(api, source.requests, auth_extras_key=AUTH_EXTRAS_KEY)
            if include_raw and api.raw:
                raw["rest"] = api.raw

        # WSDL interfaces: delegate each located WSDL once; declare the rest from the project.
        delegated: Dict[str, CanonicalApi] = {}
        wsdl_services: Dict[str, List[Service]] = {}
        services = list(api.services)
        types = list(api.types)
        servers = list(api.servers)
        for interface in source.wsdl_interfaces:
            if interface.wsdl is not None and interface.wsdl_key:
                if interface.wsdl_key not in delegated:
                    wsdl_api = WsdlNormalizer().normalize(interface.wsdl, include_raw=False)
                    delegated[interface.wsdl_key] = wsdl_api
                    services.extend(wsdl_api.services)
                    types.extend(wsdl_api.types)
                    servers.extend(wsdl_api.servers)
                    if include_raw:
                        raw.setdefault("wsdl", {})[interface.wsdl_key] = interface.wsdl.raw
                wsdl_services[interface.name] = delegated[interface.wsdl_key].services
            else:
                declared = _declared_service(interface)
                services.append(declared)
                wsdl_services[interface.name] = [declared]

        api.services = list({service.key: service for service in reversed(services)}.values())
        api.types = list({type_.key: type_ for type_ in reversed(types)}.values())
        if not source.observations:
            namespaces = {wsdl_api.identity.namespace for wsdl_api in delegated.values()}
            api.identity = ApiIdentity(
                name=source.title, namespace=next(iter(namespaces)) if len(namespaces) == 1 else None
            )

        extra_servers = [
            Server(url=url, description=f"SoapUI endpoint of {interface}") for interface, url in source.endpoints
        ] + [
            Server(
                url=url,
                description=f"{environment} environment ({service})" if service else f"{environment} environment",
            )
            for environment, service, url in source.environments
        ]
        templates = template_servers(
            source.server_variables, describe=lambda name: f"SoapUI property expansion `${{{name}}}`."
        )
        api.servers = _merge_servers(servers, extra_servers + templates)
        api.raw = raw or None if include_raw else None

        index = _OperationIndex(source, api, wsdl_services)
        suites = [
            {
                **{key: value for key, value in suite.items() if key != "cases" and value not in (None, False, [])},
                "cases": [
                    {
                        **{
                            key: value
                            for key, value in case.items()
                            if key != "steps" and value not in (None, False, [])
                        },
                        "steps": [index.step(step) for step in case["steps"]],
                    }
                    for case in suite["cases"]
                ],
            }
            for suite in source.test_suites
        ]

        extras = dict(api.extras)
        if schemes:
            extras["inferred_auth_schemes"] = sorted(set(extras.get("inferred_auth_schemes") or []) | schemes)
        declared_tests = build_declared_tests(FORMAT_KEY, suites)
        if declared_tests is not None:
            extras[DECLARED_TESTS_EXTRAS_KEY] = declared_tests
        extras[SOAPUI_EXTRAS_KEY] = {
            **({"soapui_version": source.soapui_version} if source.soapui_version else {}),
            "interfaces": [{"name": name, "kind": "rest"} for name in source.rest_interfaces]
            + [_interface_record(interface) for interface in source.wsdl_interfaces],
            "environments": sorted({environment for environment, _, _ in source.environments}),
            "properties": [prop.as_dict() for prop in source.properties],
            "mock_services": list(source.mock_services),
            "requests": len(source.requests),
            "capability_limits": _capability_limits(source),
        }
        api.extras = extras
        return normalize_ordering(api)
