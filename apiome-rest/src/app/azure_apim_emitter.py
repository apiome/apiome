"""Azure API Management emitter: canonical model → definition + policy XML — FMT-7.7 (#5461).

The inverse of :class:`app.azure_apim_import_source.AzureApimImportSource`. An APIM API is an
OpenAPI definition plus policy documents scoped to the API and to its operations, so the
export is a file set:

* ``openapi.json`` — the OpenAPI 3.0 projection of the model (paths, parameters and schemas
  survive), first in the set so it is the root an APIM import reads;
* ``policy.xml`` — the API-scope policy: the four pipeline sections, each inheriting
  ``<base />``, and a ``set-backend-service`` naming the upstream when every operation shares
  one;
* ``operations/{operationId}.xml`` — an operation-scope policy for each operation whose
  upstream differs from the API's.

When the model came from an APIM import, the policy documents it read are re-emitted
**verbatim** under the paths it read them from (the canonical model interprets policies into
extras but cannot rebuild their XML, and the original is the faithful answer). Otherwise the
policies are derived from the recorded upstreams, reported as derived. Gateway auth (a JWT,
a key) needs configuration — an OpenID configuration URL, the subscription a key belongs to —
that the canonical model does not carry, so it is a declared loss rather than an invented
``validate-jwt``; so are routing policies recorded by name only.

:func:`validate_azure_apim_bundle` is the product gate: an OpenAPI 3.0 definition, every
policy document a ``<policies>`` root with the four sections in order, every policy element a
documented APIM policy, every operation policy named after a definition ``operationId``, every
``set-backend-service`` base URL absolute — plus a re-import of the whole set.
"""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

from .azure_apim_policies import KNOWN_POLICIES, POLICY_ROOT, SECTIONS
from .canonical_model import ApiParadigm, CanonicalApi, Operation
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .gateway_emit_common import (
    later_duplicates,
    openapi_security_from_records,
    operation_upstream,
    record_method_path_collisions,
)
from .openapi_emitter import OpenApiEmitOptions, OpenApiEmitter

__all__ = [
    "AZURE_APIM_FORMAT_KEY",
    "AzureApimEmitOptions",
    "AzureApimEmitter",
    "AzureApimFidelityRulePack",
    "azure_apim_bundle_violations",
    "validate_azure_apim_bundle",
]

#: Format / emitter key (the importer's key).
AZURE_APIM_FORMAT_KEY = "azure-apim"

_LABEL = "Azure API Management export"

#: Where the API-scope policy goes.
_API_POLICY = "policy.xml"

#: Methods of an OpenAPI path item.
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

#: The non-standard methods the OpenAPI projection parks under this key in a 3.0 document.
_ADDITIONAL_OPERATIONS = "x-apiome-additional-operations"


class AzureApimFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Azure API Management export (FMT-7.7).

    The definition is OpenAPI 3.0, so the profile-derived verdicts hold for types and
    constraints. An operation with no HTTP binding has no APIM operation to become.
    """

    target_label = "Azure API Management"

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """An operation with no HTTP binding is dropped."""
        if not operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} operations are HTTP methods; operation {operation.key!r} "
                "declares no HTTP binding and is dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        if (operation.http_method or "").upper() == "ANY":
            return FidelityVerdict.drop(
                message=f"{self.target_label} operations name one HTTP method; the any-method operation "
                f"{operation.key!r} is dropped",
                target_mapping="any-method operation → dropped",
            )
        if operation.key in getattr(self, "_duplicates", set()):
            return FidelityVerdict.drop(
                message=f"{self.target_label} holds one operation per method and path; {operation.key!r} "
                "repeats an earlier one and is merged into it",
                target_mapping="duplicate operation → dropped",
            )
        if getattr(self, "_source_format", None) != AZURE_APIM_FORMAT_KEY:
            return FidelityVerdict.approx(
                message=f"operation carried to {self.target_label}, but it is rebuilt through the OpenAPI 3.0 "
                "projection with a gateway backend attached, and gateway route attributes of the source are "
                "not carried",
                target_mapping="operation → rebuilt operation",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")

    def evaluate(self, api: CanonicalApi):  # type: ignore[override]
        """Remember the source format, then walk the model."""
        self._source_format = api.format
        self._duplicates = later_duplicates(api)
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi):  # type: ignore[override]
        """A model from another format comes back as this product's artifact (format, report)."""
        verdicts = list(super().root_verdicts(api))
        if api.format != AZURE_APIM_FORMAT_KEY:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"the artifact is rebuilt as a {self.target_label} export; its format and gateway "
                    "report come back as this product's",
                    target_mapping="artifact → rebuilt artifact",
                )
            )
        return verdicts


class AzureApimEmitOptions(EmitOptions):
    """Per-target options for :class:`AzureApimEmitter`."""

    pretty_print: bool = True


def _policy_document(sections: Mapping[str, Sequence[str]]) -> str:
    """A policy document with the four sections, each inheriting ``<base />`` first."""
    lines = ["<policies>"]
    for section in SECTIONS:
        lines.append(f"  <{section}>")
        lines.append("    <base />")
        lines.extend(f"    {element}" for element in sections.get(section, ()))
        lines.append(f"  </{section}>")
    lines.append("</policies>")
    return "\n".join(lines) + "\n"


#: Rate-limit record key → policy attribute.
_LIMIT_ATTRIBUTES = (
    ("calls", "calls"),
    ("renewalPeriodSeconds", "renewal-period"),
    ("bandwidthKilobytes", "bandwidth"),
    ("counterKey", "counter-key"),
    ("incrementCondition", "increment-condition"),
)


def _limit_element(record: Mapping[str, Any]) -> Optional[str]:
    """A rate-limit / quota record (as an APIM import writes it) back as its policy element."""
    name = record.get("policy")
    if name not in ("rate-limit", "rate-limit-by-key", "quota", "quota-by-key"):
        return None
    attributes = " ".join(
        f"{attribute}={quoteattr(str(record[key]))}"
        for key, attribute in _LIMIT_ATTRIBUTES
        if record.get(key) is not None
    )
    return f"<{name} {attributes} />" if attributes else f"<{name} />"


def _ip_filter_element(record: Mapping[str, Any]) -> str:
    """An access record back as the ``ip-filter`` policy."""
    inner = "".join(f"<address>{escape(str(address))}</address>" for address in record.get("addresses") or [])
    inner += "".join(
        f"<address-range from={quoteattr(str(r.get('from')))} to={quoteattr(str(r.get('to')))} />"
        for r in record.get("addressRanges") or []
        if isinstance(r, Mapping)
    )
    return f"<ip-filter action={quoteattr(str(record.get('action') or 'allow'))}>{inner}</ip-filter>"


def _cors_element(record: Mapping[str, Any]) -> str:
    """A CORS record back as the ``cors`` policy."""
    parts = [f"<cors allow-credentials={quoteattr('true' if record.get('allowCredentials') else 'false')}>"]
    for key, container, item in (
        ("allowOrigins", "allowed-origins", "origin"),
        ("allowMethods", "allowed-methods", "method"),
        ("allowHeaders", "allowed-headers", "header"),
        ("exposeHeaders", "expose-headers", "header"),
    ):
        values = record.get(key) or []
        if values:
            age = (
                f" preflight-result-max-age={quoteattr(str(record['maxAge']))}"
                if key == "allowMethods" and record.get("maxAge") is not None
                else ""
            )
            inner = "".join(f"<{item}>{escape(str(value))}</{item}>" for value in values)
            parts.append(f"<{container}{age}>{inner}</{container}>")
    parts.append("</cors>")
    return "".join(parts)


class _ApimWriter:
    """Build the definition and policy documents of one export."""

    def __init__(self, api: CanonicalApi, options: AzureApimEmitOptions) -> None:
        self.api = api
        self.options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.operations: Dict[Tuple[str, str], Operation] = {
            ((op.http_method or "").upper(), op.http_path or ""): op for op in api.operations() if op.http_path
        }

    def build(self) -> List[EmittedFile]:
        """The emitted files, definition first."""
        if not self.operations:
            raise ValueError(
                "Azure API Management export requires at least one HTTP operation: an APIM API is a set "
                "of HTTP operations, and a model with none has nothing to declare."
            )
        record_method_path_collisions(self.api, self.losses, label="APIM definition")
        projection = OpenApiEmitter().emit(self.api, opts=OpenApiEmitOptions(openapi_version="3.0"))
        for loss in projection.losses:
            self.losses.record(loss.kind, loss.subject, loss.detail, loss.pointer)
        content = projection.files[0].content
        definition = copy.deepcopy(content if isinstance(content, dict) else json.loads(str(content)))
        operation_ids = self._operation_ids(definition)
        self._definition_security(definition)
        policies = self._verbatim_policies() or self._derived_policies(operation_ids)
        self._declare_auth_losses()
        text = json.dumps(definition, indent=2 if self.options.pretty_print else None, ensure_ascii=False) + "\n"
        files = [EmittedFile(path="openapi.json", content=text, media_type="application/json")]
        files.extend(EmittedFile(path=path, content=xml, media_type="application/xml") for path, xml in policies)
        return files

    def _operation_ids(self, definition: Dict[str, Any]) -> Dict[Tuple[str, str], str]:
        """``(METHOD, path)`` → the ``operationId`` the definition gives each operation."""
        ids: Dict[Tuple[str, str], str] = {}
        for path, item in (definition.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            extra = item.get(_ADDITIONAL_OPERATIONS)
            if isinstance(extra, dict):
                for method in list(extra):
                    self.losses.record(
                        LossKind.NA,
                        "unsupported-method",
                        f"{method} {path}: an APIM operation needs a concrete HTTP method; the operation "
                        "is not emitted.",
                        f"{method} {path}",
                    )
                item.pop(_ADDITIONAL_OPERATIONS)
            for method in _HTTP_METHODS:
                op = item.get(method)
                if isinstance(op, dict) and isinstance(op.get("operationId"), str):
                    ids[(method.upper(), path)] = op["operationId"]
        return ids

    def _definition_security(self, definition: Dict[str, Any]) -> None:
        """Write back the security schemes the source definition declared (subscription keys …)."""
        for path, item in (definition.get("paths") or {}).items():
            for method, op in item.items() if isinstance(item, dict) else ():
                if method not in _HTTP_METHODS or not isinstance(op, dict):
                    continue
                operation = self.operations.get((method.upper(), path))
                records = operation.extras.get("security") if operation is not None else None
                if isinstance(records, list):
                    declared = [r for r in records if isinstance(r, Mapping) and r.get("derivedFrom") == "definition"]
                    openapi_security_from_records(definition, op, declared)
                if operation is not None and operation.name == f"{method.upper()} {path}":
                    self.losses.record(
                        LossKind.INFERRED,
                        "synthesized-operation-id",
                        f"{method.upper()} {path}: an APIM operation needs a name, so it was given the "
                        f"operationId {op.get('operationId')!r}; a re-import names the operation after it.",
                        operation.key,
                    )

    def _verbatim_policies(self) -> List[Tuple[str, str]]:
        """The policy documents an APIM import read, unchanged, when the model came from one."""
        raw = self.api.raw if isinstance(self.api.raw, dict) else {}
        members = raw.get("policies") if raw.get("kind") in ("definition", "policy") else None
        if not isinstance(members, list):
            return []
        policies = []
        for index, member in enumerate(members):
            if not isinstance(member, Mapping) or not isinstance(member.get("xml"), str):
                continue
            path = str(member.get("path") or (_API_POLICY if index == 0 else f"policy-{index}.xml"))
            policies.append((path, member["xml"]))
            self.tracker.record(f"/{path}", Provenance.SOURCE, "Policy document recorded by the APIM import.")
        return policies

    def _derived_policies(self, operation_ids: Dict[Tuple[str, str], str]) -> List[Tuple[str, str]]:
        """Policies rebuilt from what the model records, each at the scope it was recorded.

        An APIM import records its policy facts (backend, rate limits, rewrites, CORS, the
        preserved XML of policies with no canonical form) with the scope they came from, so they
        are written back there: API scope into ``policy.xml``, operation scope into
        ``operations/{operationId}.xml``. A model from anywhere else contributes its upstream as a
        ``set-backend-service``. Product- and global-scope facts belong to policies this export
        does not write, and are declared.
        """
        api_sections: Dict[str, List[str]] = {section: [] for section in SECTIONS}
        op_sections: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        upstreams = {coordinate: operation_upstream(self.api, op) for coordinate, op in self.operations.items()}
        counts: Dict[str, int] = {}
        for url in upstreams.values():
            if url:
                counts[url] = counts.get(url, 0) + 1
        shared = max(counts, key=lambda url: (counts[url], url)) if counts else None
        if shared:
            api_sections["inbound"].append(f"<set-backend-service base-url={quoteattr(shared)} />")
            self.tracker.record(f"/{_API_POLICY}", Provenance.INFERRED, "Backend from the model's recorded upstream.")
        else:
            self.losses.record(
                LossKind.INFERRED,
                "no-backend",
                "The model records no upstream, so the API policy names no backend; set the API's web "
                "service URL before publishing.",
                "",
            )

        def add(scope: Optional[str], coordinate: Tuple[str, str], section: str, element: str) -> None:
            if scope in (None, "api"):
                if element not in api_sections[section]:
                    api_sections[section].append(element)
            elif scope == "operation":
                bucket = op_sections.setdefault(coordinate, {name: [] for name in SECTIONS})
                if element not in bucket[section]:
                    bucket[section].append(element)
            else:
                self.losses.record(
                    LossKind.NA,
                    "policy-scope-not-emitted",
                    f"A {scope}-scope policy fact ({element[:60]}) belongs to a policy this export does not write.",
                    "",
                )

        report = self.api.extras.get("azure_apim") if isinstance(self.api.extras.get("azure_apim"), Mapping) else {}
        for entry in report.get("unmapped") or []:
            if isinstance(entry, Mapping) and entry.get("scope") == "api" and isinstance(entry.get("xml"), str):
                add("api", ("", ""), str(entry.get("section") or "inbound"), entry["xml"])
        for coordinate, operation in sorted(self.operations.items()):
            url = upstreams[coordinate]
            if url and url != shared:
                add("operation", coordinate, "inbound", f"<set-backend-service base-url={quoteattr(url)} />")
            for record in operation.extras.get("rate_limits") or []:
                element = _limit_element(record) if isinstance(record, Mapping) else None
                if element is not None and record.get("derivedFrom") == "policy":
                    add(record.get("policyScope"), coordinate, "inbound", element)
            rewrite = operation.extras.get("rewrite")
            if isinstance(rewrite, Mapping) and rewrite.get("derivedFrom") == "policy":
                if isinstance(rewrite.get("uriTemplate"), str):
                    add(
                        rewrite.get("policyScope"),
                        coordinate,
                        "inbound",
                        f"<rewrite-uri template={quoteattr(rewrite['uriTemplate'])} />",
                    )
                if isinstance(rewrite.get("method"), str):
                    add(
                        rewrite.get("policyScope"),
                        coordinate,
                        "inbound",
                        f"<set-method>{escape(rewrite['method'])}</set-method>",
                    )
            for record in operation.extras.get("access") or []:
                if (
                    isinstance(record, Mapping)
                    and record.get("kind") == "ip-filter"
                    and record.get("derivedFrom") == "policy"
                ):
                    add(record.get("policyScope"), coordinate, "inbound", _ip_filter_element(record))
            backend = operation.extras.get("backend")
            if isinstance(backend, Mapping):
                auth = backend.get("authentication")
                if isinstance(auth, Mapping) and auth.get("type") == "certificate" and auth.get("thumbprint"):
                    add(
                        backend.get("policyScope"),
                        coordinate,
                        "inbound",
                        f"<authentication-certificate thumbprint={quoteattr(str(auth['thumbprint']))} />",
                    )
                if backend.get("derivedFrom") == "definition" and url == shared:
                    self.losses.record(
                        LossKind.INFERRED,
                        "service-url-as-policy",
                        f"{coordinate[0]} {coordinate[1]}: the API's service URL is written as a "
                        "set-backend-service policy, which a re-import records as policy-derived.",
                        operation.key,
                    )
            cors = operation.extras.get("cors")
            if isinstance(cors, Mapping) and cors.get("derivedFrom") == "policy":
                add(cors.get("policyScope"), coordinate, "inbound", _cors_element(cors))
            own = operation.extras.get("azure_apim") if isinstance(operation.extras.get("azure_apim"), Mapping) else {}
            for entry in own.get("unmapped") or []:
                if isinstance(entry, Mapping) and isinstance(entry.get("xml"), str):
                    add("operation", coordinate, str(entry.get("section") or "inbound"), entry["xml"])
            for record in operation.extras.get("security") or []:
                if isinstance(record, Mapping) and record.get("derivedFrom") == "policy":
                    self.losses.record(
                        LossKind.NA,
                        "auth-policy-not-emitted",
                        f"{coordinate[0]} {coordinate[1]}: the {record.get('policy') or record.get('scheme')!r} "
                        "authentication policy is recorded as a canonical scheme, not as its XML; it is not "
                        "re-emitted.",
                        operation.key,
                    )
        policies = [(_API_POLICY, _policy_document(api_sections))]
        for coordinate, sections in sorted(op_sections.items()):
            if coordinate in operation_ids:
                policies.append((f"operations/{operation_ids[coordinate]}.xml", _policy_document(sections)))
        return policies

    def _declare_auth_losses(self) -> None:
        """Gateway auth hints need configuration the canonical model does not carry."""
        for coordinate, operation in sorted(self.operations.items()):
            for hint in operation.extras.get("security") or []:
                if isinstance(hint, Mapping) and hint.get("derivedFrom") is None:
                    self.losses.record(
                        LossKind.NA,
                        "auth-not-emitted",
                        f"{coordinate[0]} {coordinate[1]}: authentication {hint.get('plugin')!r} "
                        f"({hint.get('scheme') or 'no canonical scheme'}) needs configuration (an OpenID "
                        "configuration, a product subscription) the model does not carry; no policy is "
                        "emitted for it.",
                        operation.key,
                    )


class AzureApimEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an APIM definition with its policy documents."""

    key = AZURE_APIM_FORMAT_KEY
    format = AZURE_APIM_FORMAT_KEY
    label = "Azure API Management"
    description = (
        "Export as an Azure API Management API: the OpenAPI 3.0 definition (openapi.json) with its "
        "API-scope policy.xml and operation policies — the recorded ones verbatim, or a "
        "set-backend-service to the recorded upstream."
    )
    icon = "cloud-cog"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = AzureApimEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """OpenAPI 3.0 underneath: operations, unions, nullability and constraints carry."""
        return CapabilityProfile(
            operations=True, events=False, unions=True, nullability=True, constraints=True, field_identity=False
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the APIM degradation rules."""
        return AzureApimFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[AzureApimEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit ``api`` as a definition plus policy documents.

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            ValueError: When ``api`` has no HTTP operation.
        """
        from .emitter import EmitOptionsError

        try:
            options = (
                opts
                if isinstance(opts, AzureApimEmitOptions)
                else AzureApimEmitOptions.model_validate(opts.model_dump() if opts else {})
            )
        except ValueError as exc:
            raise EmitOptionsError(f"Invalid Azure API Management emit options: {exc}") from exc
        writer = _ApimWriter(api, options)
        files = writer.build()
        return EmitResult(
            files=files,
            media_type="application/json",
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


# ===========================================================================
# Product gate
# ===========================================================================


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


#: Control-flow policies whose children are policies too.
_CONTAINER_POLICIES = frozenset({"choose", "when", "otherwise", "retry"})


def _policies_of(root: ET.Element) -> List[ET.Element]:
    """The policy elements of a document: each section's children, through control flow."""
    found: List[ET.Element] = []
    pending = [child for section in root if _local(section.tag) in SECTIONS for child in section]
    while pending:
        element = pending.pop(0)
        found.append(element)
        if _local(element.tag) in _CONTAINER_POLICIES:
            pending.extend(element)
    return found


def azure_apim_bundle_violations(files: Mapping[str, str]) -> List[str]:
    """The APIM import rules an emitted file set breaks.

    Args:
        files: Member path → text.

    Returns:
        One message per violation; empty when valid.
    """
    from .azure_apim_import_source import policy_member_scope

    errors: List[str] = []
    definition_text = files.get("openapi.json")
    if definition_text is None:
        return ["openapi.json: the set needs its OpenAPI definition"]
    definition = json.loads(definition_text)
    if not str(definition.get("openapi") or "").startswith("3.0"):
        errors.append("openapi.json: APIM imports OpenAPI 3.0 definitions")
    operation_ids = {
        op.get("operationId")
        for item in (definition.get("paths") or {}).values()
        if isinstance(item, Mapping)
        for method, op in item.items()
        if method in _HTTP_METHODS and isinstance(op, Mapping)
    }
    for path, text in files.items():
        if not path.endswith(".xml"):
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            errors.append(f"{path}: not well-formed XML ({exc})")
            continue
        if _local(root.tag) != POLICY_ROOT:
            errors.append(f"{path}: a policy document's root is <policies>")
            continue
        sections = [_local(child.tag) for child in root]
        if [section for section in SECTIONS if section in sections] != [s for s in sections if s in SECTIONS] or set(
            sections
        ) - set(SECTIONS):
            errors.append(f"{path}: <policies> holds only inbound, backend, outbound and on-error, in that order")
        for policy in _policies_of(root):
            name = _local(policy.tag)
            if name not in KNOWN_POLICIES:
                errors.append(f"{path}: <{name}> is not a documented APIM policy")
            base_url = policy.get("base-url")
            if name == "set-backend-service" and base_url is not None:
                if urlsplit(base_url).scheme not in ("http", "https") and "{{" not in base_url:
                    errors.append(f"{path}: set-backend-service base-url must be an absolute http(s) URL")
        scope, name = policy_member_scope(path)
        if scope == "operation" and name not in operation_ids:
            errors.append(f"{path}: no operation in the definition has operationId {name!r}")
    return errors


def validate_azure_apim_bundle(files: Mapping[str, str], *, source_label: str = "emitted") -> None:
    """Validate an emitted APIM file set.

    Raises:
        ValueError: When the set does not re-import, or breaks an APIM import rule.
    """
    from .azure_apim_import_source import AzureApimImportSource
    from .fileset import IntakeFileset
    from .import_source import ImportSourceError

    try:
        AzureApimImportSource().parse_fileset(
            IntakeFileset.from_members(dict(files), root="openapi.json"), source_label=source_label
        )
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Azure API Management export: {exc}") from exc
    violations = azure_apim_bundle_violations(files)
    if violations:
        raise ValueError("Invalid Azure API Management export: " + "; ".join(violations))
