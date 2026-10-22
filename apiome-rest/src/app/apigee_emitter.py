"""Apigee emitter: canonical model → an API proxy bundle — FMT-7.7 (#5461).

The inverse of :class:`app.apigee_import_source.ApigeeImportSource`. An Apigee API proxy is a
bundle of ``apiproxy/`` XML, so the export is a file set, manifest first:

* ``apiproxy/<name>.xml`` — the ``APIProxy`` manifest (display name, policy, proxy and target
  inventories);
* ``apiproxy/proxies/default.xml`` — one ``ProxyEndpoint`` with base path ``/`` and a
  ``Flow`` per operation whose ``Condition`` is the pair the importer reduces:
  ``(proxy.pathsuffix MatchesPath "/orders/*") and (request.verb = "GET")``. An operation
  matching any method gets the path condition alone;
* ``apiproxy/targets/<target>.xml`` — a ``TargetEndpoint`` per planned service (from the shared
  projection, :func:`app.gateway_config_emitter.plan_gateway_config`), whose
  ``HTTPTargetConnection`` URL is the recorded upstream (a placeholder, reported, when there is
  none), and ``RouteRule``\\ s sending each service's flows to its target;
* ``apiproxy/policies/<policy>.xml`` — ``VerifyAPIKey`` for an ``apiKey`` scheme and ``OAuthV2``
  (``VerifyAccessToken``) for ``oauth2`` / ``bearer``, attached as a request step of every flow
  that carries the scheme.

When the model came from an Apigee import, the bundle it read is re-emitted **verbatim** — the
canonical model interprets flows and policies into extras but cannot rebuild their XML.

Declared losses: ``MatchesPath`` names no path parameter (``*`` re-imports as
``{segmentN}``), a prefix match is written as an exact ``MatchesPath`` (widen it with
``/**``), header / query match conditions and routing policies recorded by name only are not
emitted, and the artifact keeps its title as the manifest's ``DisplayName``.

:func:`validate_apigee_bundle` is the product gate: a manifest whose inventories name files
that exist, every flow conditioned, every step naming a policy file, every route rule naming a
target that exists, every target with a URL or load balancer — plus a re-import of the bundle.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from xml.sax.saxutils import escape, quoteattr

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import CapabilityProfile, EmitOptions, EmitResult, EmittedFile, Emitter, LossKind, Provenance
from .fidelity_rulepack import CapabilityRulePack
from .gateway_config_model import GatewayAuthHint, GatewayMatch, GatewayRoute, GatewayServiceDef
from .gateway_emit_common import (
    ROUTING_SURFACE_PROFILE,
    GatewayEmitOptions,
    GatewayEmitPlan,
    RoutingSurfaceRulePack,
    coerce_gateway_options,
    files_result,
)

__all__ = [
    "APIGEE_FORMAT_KEY",
    "ApigeeEmitOptions",
    "ApigeeEmitter",
    "ApigeeFidelityRulePack",
    "apigee_bundle_violations",
    "validate_apigee_bundle",
]

#: Format / emitter key (the importer's key).
APIGEE_FORMAT_KEY = "apigee"

_LABEL = "Apigee API proxy bundle"

#: ``{name}`` template parameter.
_PARAM_RE = re.compile(r"\{[^}/]+\}")

#: Characters an Apigee entity name (proxy, endpoint, policy) may carry.
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

#: Canonical scheme → (policy type, policy name, element body).
_AUTH_POLICIES: Dict[str, Tuple[str, str]] = {
    "apiKey": ("VerifyAPIKey", "verify-api-key"),
    "oauth2": ("OAuthV2", "verify-access-token"),
    "bearer": ("OAuthV2", "verify-access-token"),
}


class ApigeeFidelityRulePack(RoutingSurfaceRulePack):
    """Fidelity rules for Apigee proxy export (FMT-7.7). The title survives as ``DisplayName``."""

    target_label = _LABEL
    has_title_field = True
    target_flavor = APIGEE_FORMAT_KEY
    carries_policies = False
    carries_value_matches = False
    carries_hosts = False
    merges_duplicate_routes = True

    def evaluate(self, api: CanonicalApi):  # type: ignore[override]
        """Note whether the bundle an Apigee import read is on the model (then it is re-emitted verbatim)."""
        raw = api.raw if isinstance(api.raw, dict) else {}
        self._verbatim = (
            api.format == APIGEE_FORMAT_KEY and isinstance(raw.get("members"), Mapping) and bool(raw["members"])
        )
        return super().evaluate(api)

    def route_rewrites(self, operation: Any) -> List[str]:
        """An Apigee model without its recorded bundle is rebuilt: flows and policies are re-derived."""
        if getattr(self, "_verbatim", False):
            return []
        reasons = super().route_rewrites(operation)
        if getattr(self, "_source_format", None) == APIGEE_FORMAT_KEY:
            reasons.append(
                "the bundle it came from is not on the model, so its flow, condition and policy attachments "
                "are rebuilt"
            )
        return reasons


class ApigeeEmitOptions(GatewayEmitOptions):
    """Per-target options for :class:`ApigeeEmitter`."""

    proxy_name: Optional[str] = None


def _entity(value: str, *, fallback: str) -> str:
    """An Apigee entity name."""
    name = _NAME_RE.sub("-", value).strip("-.")
    return name[:255] or fallback


def _matches_path(template: str) -> str:
    """A path template as a ``MatchesPath`` pattern (``{x}`` → ``*``)."""
    return _PARAM_RE.sub("*", template)


def _condition(match: GatewayMatch) -> str:
    """The flow condition the importer reduces back to a path and verb."""
    template = match.path.template if match.path is not None else "/"
    path = f'(proxy.pathsuffix MatchesPath "{_matches_path(template)}")'
    if match.method:
        return f'{path} and (request.verb = "{match.method}")'
    return path


class _ApigeeWriter:
    """Build the bundle members of one export."""

    def __init__(self, api: CanonicalApi, options: ApigeeEmitOptions) -> None:
        self.api = api
        self.options = options
        self.plan = GatewayEmitPlan(api, flavor=APIGEE_FORMAT_KEY, label=_LABEL, service_naming=options.service_naming)
        self.plan.declare_global_plugin_losses()

    # --- verbatim ----------------------------------------------------------------------

    def verbatim(self) -> Optional[List[Tuple[str, str]]]:
        """The bundle an Apigee import read, unchanged, when the model came from one."""
        raw = self.api.raw if isinstance(self.api.raw, dict) else {}
        members = raw.get("members")
        if self.api.format != APIGEE_FORMAT_KEY or not isinstance(members, Mapping) or not members:
            return None
        ordered = sorted(members, key=lambda path: (path.count("/"), path))
        for path in ordered:
            self.plan.tracker.record(f"/{path}", Provenance.SOURCE, "Bundle member recorded by the Apigee import.")
        return [(str(path), str(members[path])) for path in ordered]

    # --- synthesis ---------------------------------------------------------------------

    def build(self) -> List[Tuple[str, str]]:
        """The bundle members, manifest first."""
        verbatim = self.verbatim()
        if verbatim is not None:
            return verbatim
        plan = self.plan
        document = plan.document
        proxy = _entity(self.options.proxy_name or document.title or "api-proxy", fallback="api-proxy")
        services = {service.name: service for service in document.services}
        targets: Dict[str, str] = {}
        for route in document.routes:
            service = route.service_name or "default"
            targets.setdefault(service, _entity(service, fallback="default"))
        policies: Dict[str, str] = {}
        flows: List[str] = []
        route_rules: Dict[str, List[str]] = {}
        seen: Dict[str, str] = {}
        for route in document.routes:
            self._declare_route_losses(route)
            steps = self._auth_steps(route, policies)
            for index, match in enumerate(route.matches):
                condition = _condition(match)
                name = _entity(route.name if len(route.matches) == 1 else f"{route.name}-{index + 1}", fallback="flow")
                if condition in seen:
                    plan.losses.record(
                        LossKind.NA,
                        "duplicate-flow",
                        f"Route {route.name!r} matches the same path and verb as flow {seen[condition]!r} (they "
                        "differ only by host or a header / query condition); Apigee runs the first flow whose "
                        "condition matches, so the duplicate is not emitted.",
                        route.name,
                    )
                    continue
                seen[condition] = name
                flows.append(self._flow(name, condition, steps))
                route_rules.setdefault(route.service_name or "default", []).append(condition)
        files: List[Tuple[str, str]] = [
            (f"apiproxy/{proxy}.xml", self._manifest(proxy, sorted(policies), sorted(set(targets.values())))),
            ("apiproxy/proxies/default.xml", self._proxy_endpoint(flows, route_rules, targets)),
        ]
        for service, target in sorted(targets.items(), key=lambda item: item[1]):
            files.append((f"apiproxy/targets/{target}.xml", self._target_endpoint(target, services.get(service))))
        for name, xml in sorted(policies.items()):
            files.append((f"apiproxy/policies/{name}.xml", xml))
        return files

    def _declare_route_losses(self, route: GatewayRoute) -> None:
        """Report what a flow condition built from path and verb cannot carry."""
        plan = self.plan
        plan.declare_plugin_losses(route)
        for match in route.matches:
            if match.path is not None and match.path.kind == "prefix" and match.path.template != "/":
                plan.losses.record(
                    LossKind.INFERRED,
                    "prefix-as-exact",
                    f"Route {route.name!r} matches the prefix {match.path.template!r}; it is written as an exact "
                    'MatchesPath (append "/**" to the pattern to widen it).',
                    route.name,
                )
            if match.path is not None and match.path.param_names:
                plan.losses.record(
                    LossKind.INFERRED,
                    "unnamed-path-parameter",
                    f"Route {route.name!r}: MatchesPath has no parameter names, so "
                    f"{', '.join(match.path.param_names)} re-import as {{segment1}}, {{segment2}}…",
                    route.name,
                )
            if match.headers or match.query:
                plan.losses.record(
                    LossKind.NA,
                    "match-condition-not-emitted",
                    f"Route {route.name!r} matches on headers or query parameters; the emitted flow conditions "
                    "test path and verb only.",
                    route.name,
                )
        if route.hosts:
            plan.losses.record(
                LossKind.NA,
                "host-not-emitted",
                f"Route {route.name!r} is bound to hosts {', '.join(route.hosts)}; an Apigee proxy is bound to "
                "hosts by its environment's virtual hosts, not by the bundle.",
                route.name,
            )

    def _auth_steps(self, route: GatewayRoute, policies: Dict[str, str]) -> List[str]:
        """The policy steps a route's auth needs (policies registered on the way)."""
        steps: List[str] = []
        for hint in route.auth:
            mapped = _AUTH_POLICIES.get(hint.scheme or "")
            if mapped is None:
                self.plan.losses.record(
                    LossKind.NA,
                    "auth-not-emitted",
                    f"Authentication {hint.plugin!r} ({hint.scheme or 'no canonical scheme'}) on route "
                    f"{route.name!r} has no Apigee policy equivalent; it is not emitted.",
                    route.name,
                )
                continue
            kind, name = mapped
            policies.setdefault(name, self._auth_policy(kind, name, hint))
            if name not in steps:
                steps.append(name)
        return steps

    @staticmethod
    def _auth_policy(kind: str, name: str, hint: GatewayAuthHint) -> str:
        """One auth policy document."""
        if kind == "VerifyAPIKey":
            names = hint.detail.get("key_names") if isinstance(hint.detail, Mapping) else None
            header = str(names[0]) if isinstance(names, (list, tuple)) and names else "x-api-key"
            return (
                f'<VerifyAPIKey name="{name}">\n  <APIKey ref={quoteattr("request.header." + header)} />\n'
                "</VerifyAPIKey>\n"
            )
        return f'<OAuthV2 name="{name}">\n  <Operation>VerifyAccessToken</Operation>\n</OAuthV2>\n'

    @staticmethod
    def _flow(name: str, condition: str, steps: Sequence[str]) -> str:
        """One ``Flow``."""
        request = "".join(f"\n        <Step>\n          <Name>{escape(step)}</Name>\n        </Step>" for step in steps)
        request_block = f"<Request>{request}\n      </Request>" if steps else "<Request />"
        return (
            f"    <Flow name={quoteattr(name)}>\n      <Condition>{escape(condition)}</Condition>\n"
            f"      {request_block}\n      <Response />\n    </Flow>"
        )

    def _proxy_endpoint(self, flows: List[str], route_rules: Dict[str, List[str]], targets: Dict[str, str]) -> str:
        """The ``ProxyEndpoint``."""
        rules: List[str] = []
        services = list(route_rules)
        for service in services[:-1] if len(services) > 1 else []:
            condition = " or ".join(f"({c})" for c in route_rules[service])
            rules.append(
                f"  <RouteRule name={quoteattr(targets[service])}>\n    <Condition>{escape(condition)}</Condition>\n"
                f"    <TargetEndpoint>{escape(targets[service])}</TargetEndpoint>\n  </RouteRule>"
            )
        if len(services) > 1:
            self.plan.losses.record(
                LossKind.INFERRED,
                "route-rule-conditions",
                "Several services share the proxy, so each target endpoint is chosen by a route rule whose "
                "condition repeats its flows' conditions; the importer keeps such a condition as declared.",
                "",
            )
        last = targets[services[-1]] if services else "default"
        rules.append(
            f'  <RouteRule name="default">\n    <TargetEndpoint>{escape(last)}</TargetEndpoint>\n  </RouteRule>'
        )
        body = "\n".join(flows)
        return (
            '<ProxyEndpoint name="default">\n  <PreFlow name="PreFlow">\n    <Request />\n    <Response />\n'
            f'  </PreFlow>\n  <Flows>\n{body}\n  </Flows>\n  <PostFlow name="PostFlow">\n    <Request />\n'
            "    <Response />\n  </PostFlow>\n  <HTTPProxyConnection>\n    <BasePath>/</BasePath>\n"
            "  </HTTPProxyConnection>\n" + "\n".join(rules) + "\n</ProxyEndpoint>\n"
        )

    def _target_endpoint(self, target: str, service: Optional[GatewayServiceDef]) -> str:
        """One ``TargetEndpoint``."""
        url = None
        if service is not None:
            url = service.url
            if not url and service.host:
                port = f":{service.port}" if service.port else ""
                url = f"{service.protocol or 'http'}://{service.host}{port}{service.path or ''}"
        if not url:
            url = "https://backend.invalid"
            self.plan.losses.record(
                LossKind.INFERRED,
                "placeholder-target",
                f"Target endpoint {target!r} has no recorded upstream; its URL is a placeholder.",
                target,
            )
        return (
            f"<TargetEndpoint name={quoteattr(target)}>\n  <HTTPTargetConnection>\n"
            f"    <URL>{escape(url)}</URL>\n  </HTTPTargetConnection>\n</TargetEndpoint>\n"
        )

    def _manifest(self, proxy: str, policies: List[str], targets: List[str]) -> str:
        """The ``APIProxy`` manifest."""
        title = self.api.title or self.api.identity.name or proxy
        inventory = "".join(f"\n    <Policy>{escape(p)}</Policy>" for p in policies)
        target_list = "".join(f"\n    <TargetEndpoint>{escape(t)}</TargetEndpoint>" for t in targets)
        return (
            f"<APIProxy name={quoteattr(proxy)}>\n  <DisplayName>{escape(title)}</DisplayName>\n"
            f"  <Policies>{inventory}\n  </Policies>\n"
            "  <ProxyEndpoints>\n    <ProxyEndpoint>default</ProxyEndpoint>\n  </ProxyEndpoints>\n"
            f"  <TargetEndpoints>{target_list}\n  </TargetEndpoints>\n</APIProxy>\n"
        )


class ApigeeEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an Apigee API proxy bundle."""

    key = APIGEE_FORMAT_KEY
    format = APIGEE_FORMAT_KEY
    label = "Apigee API proxy"
    description = (
        "Export as an Apigee API proxy bundle (apiproxy/): a flow per operation conditioned on path and "
        "verb, a target endpoint per upstream, and VerifyAPIKey / OAuthV2 policies for the recorded auth."
    )
    icon = "boxes"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = ApigeeEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A proxy bundle routes and enforces policy: operations only, no payload schemas."""
        return ROUTING_SURFACE_PROFILE

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Apigee degradation rules."""
        return ApigeeFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[ApigeeEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit ``api`` as the members of an ``apiproxy/`` bundle.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            ValueError: When ``api`` has no HTTP operation.
        """
        options = coerce_gateway_options(opts, ApigeeEmitOptions, label=_LABEL)
        writer = _ApigeeWriter(api, options)  # type: ignore[arg-type]
        members = writer.build()
        files = [EmittedFile(path=path, content=text, media_type="application/xml") for path, text in members]
        return files_result(writer.plan, files, "application/xml")


# ===========================================================================
# Product gate
# ===========================================================================


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def apigee_bundle_violations(files: Mapping[str, str]) -> List[str]:
    """The Apigee bundle rules an emitted file set breaks.

    Args:
        files: Member path → text.

    Returns:
        One message per violation; empty when valid.
    """
    errors: List[str] = []
    roots: Dict[str, ET.Element] = {}
    for path, text in files.items():
        try:
            roots[path] = ET.fromstring(text)
        except ET.ParseError as exc:
            errors.append(f"{path}: not well-formed XML ({exc})")
    manifests = [path for path, root in roots.items() if _local(root.tag) == "APIProxy"]
    if len(manifests) != 1:
        return errors + ["apiproxy/: a bundle has exactly one APIProxy manifest"]
    by_kind: Dict[str, Dict[str, ET.Element]] = {"ProxyEndpoint": {}, "TargetEndpoint": {}, "policy": {}}
    for path, root in roots.items():
        kind = _local(root.tag)
        if kind in ("ProxyEndpoint", "TargetEndpoint"):
            by_kind[kind][root.get("name") or ""] = root
        elif "/policies/" in path:
            by_kind["policy"][root.get("name") or ""] = root
    manifest = roots[manifests[0]]
    for container, kind in (
        ("ProxyEndpoints", "ProxyEndpoint"),
        ("TargetEndpoints", "TargetEndpoint"),
        ("Policies", "policy"),
    ):
        listed = manifest.find(container)
        for entry in listed if listed is not None else []:
            if (entry.text or "").strip() not in by_kind[kind]:
                errors.append(f"{manifests[0]}: {container} lists {entry.text!r}, which the bundle does not contain")
    for name, proxy in by_kind["ProxyEndpoint"].items():
        connection = proxy.find("HTTPProxyConnection")
        if connection is None or not (connection.findtext("BasePath") or "").startswith("/"):
            errors.append(f"ProxyEndpoint {name}: HTTPProxyConnection needs a BasePath starting with /")
        for flow in proxy.iter("Flow"):
            if not (flow.findtext("Condition") or "").strip():
                errors.append(f"ProxyEndpoint {name}: flow {flow.get('name')!r} has no Condition")
        for step in proxy.iter("Step"):
            if (step.findtext("Name") or "").strip() not in by_kind["policy"]:
                errors.append(f"ProxyEndpoint {name}: step {step.findtext('Name')!r} names no policy in the bundle")
        rules = list(proxy.iter("RouteRule"))
        if not rules:
            errors.append(f"ProxyEndpoint {name}: at least one RouteRule is required")
        for rule in rules:
            target = (rule.findtext("TargetEndpoint") or "").strip()
            if target and target not in by_kind["TargetEndpoint"]:
                errors.append(f"ProxyEndpoint {name}: route rule {rule.get('name')!r} targets missing {target!r}")
    for name, target in by_kind["TargetEndpoint"].items():
        connection = target.find("HTTPTargetConnection")
        if connection is None or (connection.find("URL") is None and connection.find("LoadBalancer") is None):
            errors.append(f"TargetEndpoint {name}: HTTPTargetConnection needs a URL or a LoadBalancer")
    return errors


def validate_apigee_bundle(files: Mapping[str, str], *, source_label: str = "emitted") -> None:
    """Validate an emitted Apigee bundle.

    Raises:
        ValueError: When the bundle does not re-import, or breaks a bundle rule.
    """
    from .apigee_import_source import ApigeeImportSource
    from .fileset import IntakeFileset
    from .import_source import ImportSourceError

    manifest = next((path for path in files if path.count("/") == 1 and path.endswith(".xml")), next(iter(files)))
    try:
        ApigeeImportSource().parse_fileset(
            IntakeFileset.from_members(dict(files), root=manifest), source_label=source_label
        )
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Apigee bundle: {exc}") from exc
    violations = apigee_bundle_violations(files)
    if violations:
        raise ValueError("Invalid Apigee bundle: " + "; ".join(violations))
