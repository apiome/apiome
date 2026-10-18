"""Apigee proxy bundle import source — FMT-7.3 (#5457).

Reads an Apigee proxy bundle — the zip of ``apiproxy/`` XML that ``apigee.googleapis.com`` returns for
``…/apis/{api}/revisions/{rev}?format=bundle`` — or a loose ``ProxyEndpoint`` / ``TargetEndpoint``
file, or a fileset of them (a proxy endpoint with the shared flow it calls).

**What becomes what** (see :mod:`app.apigee_bundle` for the reading rules):

* each ``ProxyEndpoint`` is a service; its ``HTTPProxyConnection`` base path prefixes every route;
* each ``Flow`` whose condition reduces to a path and/or a verb is an **operation**
  (``MatchesPath "/orders/*"`` → ``/orders/{segment1}``, ``**`` → ``{path}``; no verb → ``ANY``);
* each ``TargetEndpoint`` is a **server** — its URL, or a load balancer as a URL template whose
  ``server`` variable lists the balanced servers;
* the policies a flow runs (``PreFlow`` and ``PostFlow`` steps apply to every operation) map to
  canonical **security** (``VerifyAPIKey``, ``OAuthV2``), **rate limits** (``SpikeArrest``, ``Quota``)
  and **CORS** (an ``AssignMessage`` setting ``Access-Control-*``). A step that runs under a condition
  keeps it.

**Nothing is dropped.** A condition that cannot be reduced to a path and a verb — a header test, a
variable comparison, an ``or`` — is a **declared condition**: on the operation when part of it did
reduce, otherwise on the API (``extras.apigee.declaredConditions``). A flow with no condition, and a
route rule with no target endpoint (a deliberate dead end), are declared conditions too. Ordered
route rules, fault rules, the policies the canonical model has no construct for (verbatim XML) and
step names whose policy the input does not carry are all in ``extras.apigee`` and on the coverage
ledger.

**Rejected.** A bundle with no ``ProxyEndpoint`` (``INPUT_SEMANTIC_INVALID``); a route rule naming a
target endpoint the bundle does not contain (``INPUT_REFERENCE_UNRESOLVED``) — a loose proxy endpoint
file is not checked, since its targets live elsewhere; a truncated or unsafe zip
(``INPUT_ARCHIVE_INVALID``); text that is not an Apigee document (``FORMAT_MISMATCH``).

The import routes to the catalog as a non-publishable item, like every non-OpenAPI format.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .apigee_bundle import (
    ApigeeBundle,
    BundleError,
    Endpoint,
    Step,
    child,
    classify_xml_root,
    interpret_policy,
    path_template,
    read_bundle,
    reduce_condition,
    steps_of,
    text_of,
    verbatim_xml,
)
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
    TypeRef,
)
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
)
from .normalizer import Keys

__all__ = ["APIGEE_BUNDLE_SUFFIXES", "APIGEE_EXTRAS_KEY", "ApigeeImportSource", "FORMAT_KEY"]

#: The canonical ``format`` (and adapter key) of an Apigee import.
FORMAT_KEY = "apigee"
#: Extras key of the API-level report.
APIGEE_EXTRAS_KEY = "apigee"
#: Suffixes of a proxy bundle given as raw bytes (the corpus suites read these as binary entries).
APIGEE_BUNDLE_SUFFIXES: Tuple[str, ...] = (".zip",)


def _members_from_zip(raw: bytes, label: Optional[str]) -> Dict[str, str]:
    """Unpack bundle bytes with the archive-intake sandbox (size, depth, path safety)."""
    from .archive_intake import ArchiveIntakeError, unpack_archive_members

    try:
        return unpack_archive_members(raw, source_label=label)
    except ArchiveIntakeError as exc:
        raise ImportSourceError(str(exc), code=getattr(exc, "code", None) or "INPUT_ARCHIVE_INVALID") from exc


def _read(members: Mapping[str, str]) -> ApigeeBundle:
    try:
        return read_bundle(members)
    except BundleError as exc:
        raise ImportSourceError(str(exc), code=exc.code) from exc


def _check(bundle: ApigeeBundle, label: Optional[str]) -> None:
    """Refuse what cannot be an Apigee API (see the module docstring)."""
    where = f" {label!r}" if label else ""
    if bundle.manifest is None and not bundle.proxies and not bundle.targets and not bundle.shared_flows:
        raise ImportSourceError(
            f"Document{where} is not an Apigee proxy bundle, ProxyEndpoint or TargetEndpoint.",
            code="FORMAT_MISMATCH",
        )
    if bundle.manifest is not None and not bundle.proxies:
        raise ImportSourceError(
            f"Bundle{where} has no ProxyEndpoint, so it serves no route.", code="INPUT_SEMANTIC_INVALID"
        )
    if bundle.manifest is not None:
        for proxy in bundle.proxies.values():
            for rule in proxy.root:
                if rule.tag != "RouteRule":
                    continue
                target = text_of(rule, "TargetEndpoint")
                if target and target not in bundle.targets:
                    raise ImportSourceError(
                        f"Route rule {rule.get('name')!r} of proxy endpoint {proxy.name!r} names target endpoint "
                        f"{target!r}, which the bundle does not contain.",
                        code="INPUT_REFERENCE_UNRESOLVED",
                    )


class ApigeeImportSource(ImportSource, register=True):
    """Adapter for Apigee proxy bundles and loose Apigee endpoint files."""

    key = FORMAT_KEY
    label = "Apigee proxy bundle"
    description = (
        "Import an Apigee proxy bundle (the apiproxy/ zip) or a loose ProxyEndpoint or TargetEndpoint. "
        "Flows become operations and target endpoints servers; VerifyAPIKey, OAuthV2, SpikeArrest, Quota "
        "and CORS policies map to canonical security, rate-limit and CORS metadata. Conditions that "
        "cannot be reduced to a path and verb are kept as declared conditions."
    )
    icon = "cloud"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (FORMAT_KEY,)
    file_extensions = (".xml", ".zip")

    # --- detection -------------------------------------------------------------------

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a bundle zip, or an XML text whose root is an Apigee manifest or endpoint."""
        if payload.data is not None and payload.text is None:
            data = payload.data
            if data[:2] == b"PK" and b"apiproxy/" in data[:65536]:
                return DetectionResult(confidence=0.97, format=FORMAT_KEY, reason="zip with `apiproxy/` members")
            return NO_MATCH
        kind = classify_xml_root(payload.text)
        if kind == "manifest":
            return DetectionResult(confidence=0.97, format=FORMAT_KEY, reason="`APIProxy` bundle manifest")
        if kind in ("proxy", "target", "shared-flow", "shared-flow-manifest"):
            return DetectionResult(confidence=0.95, format=FORMAT_KEY, reason=f"Apigee `{kind}` root element")
        return NO_MATCH

    # --- parsing ---------------------------------------------------------------------

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse one loose XML file (a ProxyEndpoint, TargetEndpoint or shared flow).

        Raises:
            ImportSourceError: ``INPUT_ENCODING_INVALID`` / ``INPUT_MALFORMED`` / ``INPUT_TRUNCATED``
                for unreadable XML, ``FORMAT_MISMATCH`` for anything that is not Apigee XML.
        """
        if "\x00" in raw or "�" in raw:
            raise ImportSourceError(
                f"Document {source_label!r} is not UTF-8 text (UTF-16 or binary content?)",
                code="INPUT_ENCODING_INVALID",
            )
        if not raw.lstrip("﻿ \t\r\n").startswith("<"):
            raise ImportSourceError(
                f"Document {source_label!r} is not XML, so it is not an Apigee proxy bundle or endpoint.",
                code="FORMAT_MISMATCH",
            )
        label = source_label or "endpoint.xml"
        name = label if label.lower().endswith(".xml") else f"{label}.xml"
        return self._native({name: raw}, kind="files", label=source_label)

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse an unpacked bundle, or a set of loose files (a proxy endpoint and its shared flow)."""
        if not fileset.members:
            raise ImportSourceError("Apigee fileset has no members", code="INPUT_MALFORMED")
        members = dict(fileset.members)
        kind = "bundle" if any(classify_xml_root(t) == "manifest" for t in members.values()) else "files"
        return self._native(members, kind=kind, label=source_label or fileset.root)

    def parse_bytes(self, raw: bytes, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse a proxy bundle zip (what Apigee's ``?format=bundle`` download returns).

        Raises:
            ImportSourceError: ``INPUT_ARCHIVE_INVALID`` (or a size code) for a truncated or unsafe
                archive, plus everything :meth:`parse_fileset` raises.
        """
        members = _members_from_zip(raw, source_label)
        return self._native(members, kind="bundle", label=source_label)

    @staticmethod
    def _native(members: Mapping[str, str], *, kind: str, label: Optional[str]) -> Dict[str, Any]:
        bundle = _read(members)
        _check(bundle, label)
        return {"kind": kind, "label": label, "members": dict(sorted(members.items()))}

    # --- normalization ---------------------------------------------------------------

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model from a parsed bundle (see the module docstring).

        Raises:
            ImportSourceError: When ``native_ast`` is not what the parse methods return.
        """
        if not isinstance(native_ast, Mapping) or not isinstance(native_ast.get("members"), Mapping):
            raise ImportSourceError("Not a parsed Apigee document.", code="INPUT_MALFORMED")
        bundle = _read(native_ast["members"])
        model = _Builder(bundle, str(native_ast.get("kind") or "files")).build()
        if include_raw:
            model.raw = dict(native_ast)
        return model


# ---------------------------------------------------------------------------------------
# Building the canonical model
# ---------------------------------------------------------------------------------------


class _Builder:
    """Turns an :class:`ApigeeBundle` into a :class:`CanonicalApi` and its ``extras.apigee`` report."""

    def __init__(self, bundle: ApigeeBundle, shape: str) -> None:
        self.bundle = bundle
        self.shape = shape
        self.mapped: Dict[str, int] = {}
        self.unmapped: Dict[str, Dict[str, Any]] = {}
        self.unresolved: Dict[str, List[str]] = {}
        self.declared: List[Dict[str, Any]] = []
        self.callouts: Dict[str, Optional[str]] = {}

    # --- steps -> facts ----------------------------------------------------------------

    def _expand(self, steps: List[Step]) -> List[Tuple[str, Optional[str], Optional[Any]]]:
        """Each step as ``(policy name, condition, policy element)``, shared-flow callouts expanded."""
        out: List[Tuple[str, Optional[str], Optional[Any]]] = []
        for step in steps:
            policy = self.bundle.policies.get(step.name)
            out.append((step.name, step.condition, policy))
            if policy is not None and policy.tag == "FlowCallout":
                flow = self.bundle.shared_flows.get(text_of(policy, "SharedFlowBundle") or "") or (
                    next(iter(self.bundle.shared_flows.values())) if len(self.bundle.shared_flows) == 1 else None
                )
                if flow is not None:
                    for inner in steps_of(flow):
                        condition = " and ".join(c for c in (step.condition, inner.condition) if c) or None
                        out.append((inner.name, condition, self.bundle.policies.get(inner.name)))
        return out

    def _apply(self, extras: Dict[str, Any], steps: List[Step], where: str) -> None:
        """Interpret the policies ``steps`` run and add their records to ``extras``."""
        for name, condition, policy in self._expand(steps):
            if policy is None:
                self.unresolved.setdefault(name, []).append(where)
                continue
            if policy.tag == "FlowCallout":
                # Structural: its shared flow's steps were expanded in place above.
                self.callouts.setdefault(name, text_of(policy, "SharedFlowBundle"))
                continue
            target, record = interpret_policy(name, policy)
            if record is None:
                entry = self.unmapped.setdefault(
                    name, {"name": name, "policyType": policy.tag, "xml": verbatim_xml(policy), "usedBy": []}
                )
                if where not in entry["usedBy"]:
                    entry["usedBy"].append(where)
                continue
            if condition:
                record = {**record, "condition": condition}
            self.mapped[policy.tag] = self.mapped.get(policy.tag, 0) + 1
            if target == "cors":
                extras["cors"] = record
            else:
                extras.setdefault(target, []).append(record)

    # --- endpoints -----------------------------------------------------------------------

    def _servers(self) -> Tuple[List[Server], List[Dict[str, Any]]]:
        servers: List[Server] = []
        report: List[Dict[str, Any]] = []
        for name, target in sorted(self.bundle.targets.items()):
            connection = child(target.root, "HTTPTargetConnection")
            entry: Dict[str, Any] = {"name": name}
            if connection is None:
                entry["connection"] = "none"
                report.append(entry)
                continue
            path = text_of(connection, "Path") or ""
            url = text_of(connection, "URL")
            balancer = child(connection, "LoadBalancer")
            ssl = child(connection, "SSLInfo")
            if url:
                entry["url"] = url
                servers.append(Server(url=url, name=name, description=f"Apigee target endpoint {name}."))
            elif balancer is not None:
                members = [s.get("name") for s in balancer if s.tag == "Server" and s.get("name")]
                entry["loadBalancer"] = {"servers": members, "algorithm": text_of(balancer, "Algorithm")}
                if members:
                    servers.append(
                        Server(
                            url="https://{server}" + path,
                            name=name,
                            description=f"Apigee target endpoint {name}, load-balanced across {', '.join(members)}.",
                            variables=[ServerVariable(name="server", default=members[0], enum=members)],
                        )
                    )
            if path:
                entry["path"] = path
            properties = child(connection, "Properties")
            if properties is not None:
                entry["properties"] = {p.get("name"): (p.text or "").strip() for p in properties if p.get("name")}
            if ssl is not None:
                entry["ssl"] = {
                    "enabled": (text_of(ssl, "Enabled") or "").lower() == "true",
                    "clientAuth": (text_of(ssl, "ClientAuthEnabled") or "").lower() == "true",
                }
            steps = [
                *steps_of(child(child(target.root, "PreFlow"), "Request")),
                *steps_of(child(child(target.root, "PostFlow"), "Request")),
            ]
            if steps:
                entry["steps"] = [s.name for s in steps]
                self._apply({}, steps, f"target:{name}")
            report.append(entry)
        return servers, report

    def _route_rules(self, proxy: Endpoint) -> List[Dict[str, Any]]:
        rules: List[Dict[str, Any]] = []
        for order, rule in enumerate(r for r in proxy.root if r.tag == "RouteRule"):
            condition = text_of(rule, "Condition")
            target = text_of(rule, "TargetEndpoint")
            reduced = reduce_condition(condition)
            entry: Dict[str, Any] = {"order": order, "name": rule.get("name"), "condition": condition, "target": target}
            if target is None and child(rule, "URL") is None:
                entry["target"] = None
                self.declared.append(
                    {
                        "kind": "route-without-target",
                        "proxy": proxy.name,
                        "routeRule": rule.get("name"),
                        "expression": condition,
                        "meaning": "Requests matching this rule reach no target endpoint (the proxy answers itself).",
                        "provenance": "declared",
                    }
                )
            elif reduced.unreduced:
                entry["unreduced"] = reduced.unreduced
                self.declared.append(
                    {
                        "kind": "route-condition",
                        "proxy": proxy.name,
                        "routeRule": rule.get("name"),
                        "expression": condition,
                        "unreduced": reduced.unreduced,
                        "target": target,
                        "meaning": f"Routes to target endpoint {target!r} on a condition that is not a path and verb.",
                        "provenance": "declared",
                    }
                )
            if child(rule, "URL") is not None:
                entry["url"] = text_of(rule, "URL")
            rules.append(entry)
        return rules

    def _operations(self, proxy: Endpoint, base_path: str) -> List[Operation]:
        pre = child(proxy.root, "PreFlow")
        post = child(proxy.root, "PostFlow")
        shared_steps = [
            *steps_of(child(pre, "Request")),
            *steps_of(child(pre, "Response")),
            *steps_of(child(post, "Request")),
            *steps_of(child(post, "Response")),
        ]
        operations: Dict[str, Operation] = {}
        for flow in (f for f in (child(proxy.root, "Flows") or []) if f.tag == "Flow"):
            flow_name = flow.get("name") or "flow"
            condition = text_of(flow, "Condition")
            reduced = reduce_condition(condition)
            flow_steps = [*steps_of(child(flow, "Request")), *steps_of(child(flow, "Response"))]
            if reduced.path is None and reduced.verb is None:
                self.declared.append(
                    {
                        "kind": "flow-condition" if condition else "unconditional-flow",
                        "proxy": proxy.name,
                        "flow": flow_name,
                        "expression": condition,
                        "unreduced": reduced.unreduced,
                        "meaning": (
                            "Cannot be reduced to a path and verb; the flow is kept as a declared condition."
                            if condition
                            else "Has no condition, so it runs for every request."
                        ),
                        "steps": [s.name for s in flow_steps],
                        "provenance": "declared",
                    }
                )
                self._apply({}, flow_steps, f"flow:{flow_name}")
                continue
            path, params = path_template(base_path, reduced.path)
            method = reduced.verb or "ANY"
            key = Keys.operation_http(method, path)
            if key in operations:
                self.declared.append(
                    {
                        "kind": "duplicate-route",
                        "proxy": proxy.name,
                        "flow": flow_name,
                        "expression": condition,
                        "meaning": f"Matches the same route as an earlier flow ({key}); only the first one runs.",
                        "provenance": "declared",
                    }
                )
                continue
            operation = Operation(
                key=key,
                name=flow_name,
                kind=OperationKind.REQUEST_RESPONSE,
                http_method=method,
                http_path=path,
                description=text_of(flow, "Description"),
                parameters=[
                    Parameter(
                        key=Keys.parameter(key, "path", name),
                        name=name,
                        location=ParameterLocation.PATH,
                        type=TypeRef(name="string", nullable=False),
                        required=True,
                        **({"description": "Any number of path segments (Apigee `**`)."} if greedy else {}),
                    )
                    for name, greedy in params
                ],
            )
            operation.extras["apigee"] = {"flow": flow_name, "condition": condition, "proxyEndpoint": proxy.name}
            if reduced.unreduced:
                operation.extras["declared_conditions"] = [
                    {"expression": condition, "unreduced": reduced.unreduced, "provenance": "declared"}
                ]
            self._apply(operation.extras, shared_steps, "preflow/postflow")
            self._apply(operation.extras, flow_steps, f"flow:{flow_name}")
            operations[key] = operation
        if not operations:
            # PreFlow/PostFlow policies still run; record them once even with no routes.
            self._apply({}, shared_steps, "preflow/postflow")
        return list(operations.values())

    # --- the model --------------------------------------------------------------------------

    def build(self) -> CanonicalApi:
        manifest = self.bundle.manifest
        proxy_name = (
            (manifest.get("name") if manifest is not None else None)
            or next(iter(self.bundle.proxies), None)
            or next(iter(self.bundle.targets), None)
            or "apigee-proxy"
        )
        title = text_of(manifest, "DisplayName") or proxy_name
        description = text_of(manifest, "Description") or next(
            (text_of(p.root, "Description") for p in self.bundle.proxies.values() if text_of(p.root, "Description")),
            None,
        )
        servers, targets_report = self._servers()
        services: List[Service] = []
        proxies_report: List[Dict[str, Any]] = []
        route_rules: List[Dict[str, Any]] = []
        fault_rules: List[Dict[str, Any]] = []
        for name, proxy in sorted(self.bundle.proxies.items()):
            connection = child(proxy.root, "HTTPProxyConnection")
            base_path = text_of(connection, "BasePath") or "/"
            proxies_report.append(
                {
                    "name": name,
                    "basePath": base_path,
                    "virtualHosts": [(v.text or "").strip() for v in (connection or []) if v.tag == "VirtualHost"],
                }
            )
            route_rules.extend({"proxy": name, **rule} for rule in self._route_rules(proxy))
            for rule in child(proxy.root, "FaultRules") or []:
                if rule.tag == "FaultRule":
                    fault_rules.append(
                        {
                            "proxy": name,
                            "name": rule.get("name"),
                            "condition": text_of(rule, "Condition"),
                            "steps": [s.name for s in steps_of(rule)],
                        }
                    )
            default_fault = child(proxy.root, "DefaultFaultRule")
            if default_fault is not None:
                fault_rules.append(
                    {
                        "proxy": name,
                        "name": default_fault.get("name"),
                        "default": True,
                        "steps": [s.name for s in steps_of(default_fault)],
                    }
                )
            services.append(
                Service(
                    key=name,
                    name=name,
                    description=text_of(proxy.root, "Description"),
                    operations=self._operations(proxy, base_path),
                )
            )
        model = CanonicalApi(
            paradigm=ApiParadigm.REST,
            format=FORMAT_KEY,
            protocol="http",
            identity=ApiIdentity(name=proxy_name),
            version=manifest.get("revision") if manifest is not None else None,
            title=title,
            description=description,
            servers=servers,
            services=services,
        )
        model.extras[APIGEE_EXTRAS_KEY] = {
            "provenance": "declared",
            "shape": self.shape,
            "proxyName": proxy_name,
            "revision": manifest.get("revision") if manifest is not None else None,
            "basePaths": [text_of(manifest, "BasePaths")]
            if text_of(manifest, "BasePaths")
            else [p["basePath"] for p in proxies_report],
            "proxyEndpoints": proxies_report,
            "targetEndpoints": targets_report,
            "routeRules": route_rules,
            "declaredConditions": self.declared,
            "faultRules": fault_rules,
            "policies": {name: policy.tag for name, policy in sorted(self.bundle.policies.items())},
            "sharedFlows": sorted(self.bundle.shared_flows),
            "flowCallouts": [
                {"policy": name, "sharedFlowBundle": bundle_name, "resolved": bool(self.bundle.shared_flows)}
                for name, bundle_name in sorted(self.callouts.items())
            ],
            "mapped": dict(sorted(self.mapped.items())),
            "unmapped": [self.unmapped[k] for k in sorted(self.unmapped)],
            "unresolvedSteps": {k: sorted(set(v)) for k, v in sorted(self.unresolved.items())},
            "resources": list(self.bundle.resources),
        }
        return model
