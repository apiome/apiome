"""Azure API Management import source — FMT-7.2 (#5456).

APIM carries an API **definition** plus a separate XML **policy** document per scope (global,
product, API, operation). The policies are what the gateway actually enforces — JWT validation,
rate limits and quotas, IP filters, CORS, the backend a request goes to and how its URL is
rewritten — and they exist nowhere else. This adapter reads both halves and normalizes the policy
semantics so Apiome can govern them.

**Accepted shapes**

* a **policy document** — ``<policies>`` with its ``inbound``/``backend``/``outbound``/``on-error``
  sections (read as the API scope), or a ``<policies-composition>`` of ``<policy scope="…">``
  documents;
* an **ARM template** listing ``Microsoft.ApiManagement/service/…`` resources: APIs, operations,
  API- and operation-level policies (escaped XML strings), products, backends, named values and
  version sets (:mod:`app.azure_apim_arm`);
* an **APIM-exported OpenAPI definition** (it carries the ``Ocp-Apim-Subscription-Key`` scheme or an
  ``*.azure-api.net`` server), alone or as the root of a **fileset** with its policy documents.
  Policy members are scoped by name: ``policy.xml`` / ``api.policy.xml`` is the API scope,
  ``operations/{operationId}.xml`` or ``{operationId}.policy.xml`` an operation, ``products/{name}.xml``
  a product and ``global.xml`` the service. An ARM template member contributes the backends, named
  values and products it declares.

**Definition first, then policies.** The definition is normalized by the OpenAPI path (an ARM
template's operations are first written as the OpenAPI document APIM would export), so paths,
parameters and schemas come out exactly as an OpenAPI import would. The policies are then composed
per operation — ``<base />`` expands to the parent scope at its position — and interpreted
(:mod:`app.azure_apim_policies`):

* ``validate-jwt``, ``validate-azure-ad-token``, ``check-header`` → ``operation.extras["security"]``
  (the shape :mod:`app.canonical_security` reads), next to the definition's own subscription-key
  requirement;
* ``rate-limit``, ``rate-limit-by-key``, ``quota``, ``quota-by-key`` → ``extras["rate_limits"]``;
* ``set-backend-service`` (and the backend ``authentication-*`` policies) → ``extras["backend"]``,
  and an API-scope backend URL becomes a canonical server named ``backend``;
* ``rewrite-uri``, ``set-method``, ``set-query-parameter`` → ``extras["rewrite"]``;
* ``cors`` → ``extras["cors"]``; ``ip-filter`` → ``extras["access"]``.

**Provenance.** Every record says ``provenance: "declared"`` and ``derivedFrom`` — ``"definition"``
for facts the API definition states, ``"policy"`` (with its ``policyScope``) for facts a policy
states — so the two are always told apart. Policy elements without a canonical construct
(``cache-*``, ``send-request``, ``json-to-xml``, vendor policies) are kept **verbatim** under
``api.extras["azure_apim"]["unmapped"]`` and listed on the coverage ledger, never dropped.

**References are checked.** A ``{{named-value}}`` a policy uses must be declared by the input (an
ARM ``namedValues`` resource): the value is substituted into the policy text, so without it the
policy is incomplete (``INPUT_REFERENCE_UNRESOLVED``). A ``backend-id`` is checked against the
backends the input declares; when it declares none (a lone policy document) the backend is
recorded as unresolved instead.

The import routes to the catalog as a non-publishable item, like every non-OpenAPI format.
"""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .aws_apigateway_extensions import is_openapi_document, security_for_scheme
from .azure_apim_arm import (
    ArmEstate,
    has_apim_markers,
    is_apim_arm_template,
    openapi_for_estate,
    read_arm_template,
)
from .azure_apim_policies import (
    COMPOSITION_ROOT,
    PolicyError,
    PolicyFacts,
    ScopedPolicy,
    compose,
    interpret,
    is_policy_text,
    named_value_references,
    read_composition,
    read_policy_xml,
)
from .canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Operation, Server
from .fileset import IntakeFileset
from .import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    InputKind,
    LintReport,
)
from .normalizer import Keys
from .openapi_fileset_bundle import bundle_openapi_fileset
from .openapi_import_source import OpenApiImportSource

__all__ = ["APIM_EXTRAS_KEY", "AzureApimImportSource", "FORMAT_KEY", "policy_member_scope"]

#: The canonical ``format`` (and adapter key) of an APIM import.
FORMAT_KEY = "azure-apim"
#: Extras key of the API-level report (and of an operation's own unmapped policies).
APIM_EXTRAS_KEY = "azure_apim"

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_SCOPE_ORDER = {"global": 0, "workspace": 1, "product": 2, "api": 3, "operation": 4}


def policy_member_scope(path: str) -> Tuple[str, Optional[str]]:
    """The scope a fileset policy member applies to, from its path (see the module docstring).

    Args:
        path: The member's relative POSIX path.

    Returns:
        ``(scope, name)`` — ``name`` is the operation id for ``operation``, the product name for
        ``product``, else ``None``.
    """
    parts = PurePosixPath(path).parts
    stem = parts[-1]
    for suffix in (".xml", ".policy"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    folders = [p.lower() for p in parts[:-1]]
    if "operations" in folders:
        return "operation", stem
    if "products" in folders:
        return "product", stem
    if stem.lower() in ("", "policy", "api", "api-policy"):
        return "api", None
    if stem.lower() in ("global", "service", "global-policy"):
        return "global", None
    return "operation", stem


def _check_text(text: str, label: Optional[str]) -> None:
    where = f" {label!r}" if label else ""
    if "\x00" in text or "�" in text:
        raise ImportSourceError(
            f"Document{where} is not UTF-8 text (UTF-16 or binary content?)", code="INPUT_ENCODING_INVALID"
        )


def _read_policy(text: str, label: Optional[str]) -> Any:
    try:
        return read_policy_xml(text, source_label=label)
    except PolicyError as exc:
        raise ImportSourceError(str(exc), code=exc.code) from exc


def _load_structured(text: str, label: Optional[str]) -> Any:
    """Parse JSON/YAML text with the OpenAPI loader (which maps loader errors onto the taxonomy)."""
    try:
        return OpenApiImportSource().parse(text, source_label=label)
    except ImportSourceError as exc:
        if exc.code is None and "end of stream" in str(exc):
            raise ImportSourceError(f"Document is truncated: {exc}", code="INPUT_TRUNCATED") from exc
        raise


class AzureApimImportSource(ImportSource, register=True):
    """Adapter for Azure API Management definitions and policy documents."""

    key = FORMAT_KEY
    label = "Azure API Management"
    description = (
        "Import an APIM API: its policy XML, an ARM template of APIM resources, or an exported "
        "OpenAPI definition with its policy documents. Paths and schemas import as OpenAPI would; "
        "validate-jwt, rate limits and quotas, set-backend-service, rewrite-uri, CORS and IP "
        "filters map to canonical security, rate-limit, backend, rewrite, CORS and access metadata. "
        "Unmapped policies are preserved verbatim and reported."
    )
    icon = "cloud"
    paradigm = ApiParadigm.REST
    input_kinds = (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET)
    formats = (FORMAT_KEY,)
    file_extensions = (".xml", ".json", ".yaml", ".yml")

    # --- detection -------------------------------------------------------------------

    def detect(self, payload: DetectionInput) -> DetectionResult:
        """Claim a policy document, an APIM ARM template, or an APIM-exported OpenAPI definition."""
        text = payload.text or ""
        if is_policy_text(text):
            return DetectionResult(
                confidence=0.95, format=FORMAT_KEY, reason="APIM `<policies>` document with pipeline sections"
            )
        document = payload.document
        if document is None and text:
            if "Microsoft.ApiManagement" not in text and "azure-api.net" not in text and "Ocp-Apim" not in text:
                return NO_MATCH
            try:
                document = OpenApiImportSource().parse(text, source_label=payload.filename)
            except ImportSourceError:
                return NO_MATCH
        if is_apim_arm_template(document):
            return DetectionResult(
                confidence=0.95,
                format=FORMAT_KEY,
                reason="ARM template with `Microsoft.ApiManagement/service` resources",
            )
        if is_openapi_document(document) and has_apim_markers(document):
            return DetectionResult(
                confidence=0.9,
                format=FORMAT_KEY,
                reason="OpenAPI definition exported by APIM (subscription-key scheme or azure-api.net gateway)",
            )
        return NO_MATCH

    # --- parsing ---------------------------------------------------------------------

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse one document — a policy, an ARM template or an APIM-exported definition.

        Returns:
            The native AST: ``{"kind": "policy" | "arm" | "definition", …}`` (JSON-serializable).

        Raises:
            ImportSourceError: ``INPUT_ENCODING_INVALID``, ``INPUT_MALFORMED``, ``INPUT_TRUNCATED``
                from the readers; ``FORMAT_MISMATCH`` for a document that is none of the three;
                ``INPUT_SEMANTIC_INVALID`` for a policy without pipeline sections;
                ``INPUT_REFERENCE_UNRESOLVED`` for an undeclared named value or backend.
        """
        _check_text(raw, source_label)
        if raw.lstrip("﻿ \t\r\n").startswith("<"):
            _read_policy(raw, source_label)
            native: Dict[str, Any] = {
                "kind": "policy",
                "label": source_label,
                "policies": [{"path": source_label, "xml": raw}],
            }
        else:
            document = _load_structured(raw, source_label)
            native = self._structured_native(document, source_label)
        _check_references(native)
        return native

    def parse_fileset(self, fileset: IntakeFileset, *, source_label: Optional[str] = None) -> Dict[str, Any]:
        """Parse a definition (or ARM template) with its sibling policy documents and ARM members."""
        if not fileset.members:
            raise ImportSourceError("APIM fileset has no members", code="INPUT_MALFORMED")
        policies: List[Dict[str, Any]] = []
        structured: Dict[str, Any] = {}
        for path, text in sorted(fileset.members.items()):
            _check_text(text, path)
            if text.lstrip("﻿ \t\r\n").startswith("<"):
                if is_policy_text(text) or path.lower().endswith(".xml"):
                    _read_policy(text, path)
                    policies.append({"path": path, "xml": text})
                continue
            structured[path] = _load_structured(text, path)
        # The definition is the root whenever there is one: archive intake ranks members by
        # detection confidence, so a policy or an ARM member (0.95) can outrank it (0.9).
        definitions = [p for p, d in structured.items() if is_openapi_document(d)]
        templates = [p for p, d in structured.items() if is_apim_arm_template(d)]
        if definitions:
            root = fileset.root if fileset.root in definitions else definitions[0]
        elif templates:
            root = fileset.root if fileset.root in templates else templates[0]
        else:
            root = None
        if root is None:
            if not policies:
                raise ImportSourceError(
                    "No member of the fileset is an APIM definition or policy.", code="FORMAT_MISMATCH"
                )
            native: Dict[str, Any] = {"kind": "policy", "label": source_label, "policies": policies}
        else:
            document = structured[root]
            if is_openapi_document(document):
                document = bundle_openapi_fileset(
                    IntakeFileset.from_members(
                        {p: t for p, t in fileset.members.items() if p in structured}, root=root
                    ),
                    root=root,
                )
                native = {"kind": "definition", "label": source_label or root, "definition": document}
            else:
                native = self._structured_native(document, source_label or root)
            native["policies"] = native.get("policies", []) + policies
            native["arm"] = [d for p, d in sorted(structured.items()) if p != root and is_apim_arm_template(d)]
        _check_references(native)
        return native

    @staticmethod
    def _structured_native(document: Any, label: Optional[str]) -> Dict[str, Any]:
        where = f" {label!r}" if label else ""
        if is_apim_arm_template(document):
            return {"kind": "arm", "label": label, "template": document, "policies": [], "arm": []}
        if is_openapi_document(document):
            if not has_apim_markers(document):
                raise ImportSourceError(
                    f"Document{where} is a plain OpenAPI definition with no APIM markers; import it as OpenAPI.",
                    code="FORMAT_MISMATCH",
                )
            return {"kind": "definition", "label": label, "definition": document, "policies": [], "arm": []}
        raise ImportSourceError(
            f"Document{where} is not an APIM policy, an ARM template of APIM resources, or an APIM-exported "
            "OpenAPI definition.",
            code="FORMAT_MISMATCH",
        )

    # --- normalization ---------------------------------------------------------------

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize the definition (OpenAPI path), then compose and interpret the policies.

        Raises:
            ImportSourceError: When ``native_ast`` is not what :meth:`parse` returns.
        """
        if not isinstance(native_ast, Mapping) or native_ast.get("kind") not in ("policy", "arm", "definition"):
            raise ImportSourceError("Not a parsed APIM document.", code="INPUT_MALFORMED")
        context = _Context.build(native_ast)
        if context.definition is not None:
            model = OpenApiImportSource().normalize(copy.deepcopy(context.definition), include_raw=False)
        else:
            title = "Azure API Management policy composition" if context.composition else "Azure API Management policy"
            model = CanonicalApi(
                paradigm=ApiParadigm.REST,
                format=FORMAT_KEY,
                protocol="http",
                identity=ApiIdentity(name=title),
                title=title,
            )
        model.format = FORMAT_KEY
        if include_raw:
            model.raw = dict(native_ast)
        _interpret(model, context)
        return model

    def lint(self, model: CanonicalApi) -> LintReport:
        """Lint with the OpenAPI linter when there is a definition, else the canonical-model engine."""
        raw = model.raw if isinstance(model.raw, dict) else {}
        definition = raw.get("definition")
        if raw.get("kind") == "arm" and isinstance(raw.get("template"), dict):
            definition = openapi_for_estate(read_arm_template(raw["template"]))[0]
        if isinstance(definition, dict) and isinstance(definition.get("openapi"), str):
            shadow = model.model_copy()
            shadow.raw = definition
            return OpenApiImportSource().lint(shadow)
        return super().lint(model)


# ---------------------------------------------------------------------------------------
# Context: everything the interpretation needs, gathered once
# ---------------------------------------------------------------------------------------


class _Context:
    """The definition, the estate and the scoped policies of one parsed native AST."""

    def __init__(self) -> None:
        self.shape = "policy"
        self.definition: Optional[Dict[str, Any]] = None
        self.owners: Dict[Tuple[str, str], Tuple[Optional[str], str]] = {}
        self.collisions: List[str] = []
        self.estate = ArmEstate()
        self.policies: List[ScopedPolicy] = []
        self.composition = False

    @classmethod
    def build(cls, native: Mapping[str, Any]) -> "_Context":
        ctx = cls()
        kind = native["kind"]
        templates = list(native.get("arm") or [])
        if kind == "arm":
            ctx.shape = "arm-template"
            templates.insert(0, native["template"])
        for template in templates:
            _merge_estate(ctx.estate, read_arm_template(template))
        if kind == "arm":
            ctx.definition, owners, ctx.collisions = openapi_for_estate(ctx.estate)
            ctx.owners = dict(owners)
            ctx.policies.extend(_estate_policies(ctx.estate))
        elif kind == "definition":
            ctx.shape = "definition+policy" if native.get("policies") else "definition"
            ctx.definition = native["definition"]
            for path, method, op in _definition_operations(ctx.definition):
                if isinstance(op.get("operationId"), str):
                    ctx.owners[(method.upper(), path)] = (None, op["operationId"])
            ctx.policies.extend(_estate_policies(ctx.estate))
        for member in native.get("policies") or []:
            root = read_policy_xml(member["xml"], source_label=member.get("path"))
            if root.tag.rsplit("}", 1)[-1] == COMPOSITION_ROOT:
                ctx.composition = True
                ctx.policies.extend(read_composition(root))
            elif kind == "policy" and len(native.get("policies") or []) == 1:
                ctx.policies.append(ScopedPolicy("api", root))
            else:
                scope, name = policy_member_scope(str(member.get("path") or "policy.xml"))
                ctx.policies.append(
                    ScopedPolicy(
                        scope,
                        root,
                        name=name if scope == "product" else None,
                        operation=name if scope == "operation" else None,
                    )
                )
        if kind == "policy":
            ctx.shape = "policy-composition" if ctx.composition else "policy"
        return ctx


def _merge_estate(target: ArmEstate, source: ArmEstate) -> None:
    target.service = target.service or source.service
    target.apis.extend(source.apis)
    for name, product in source.products.items():
        merged = target.products.setdefault(name, {"apis": [], "policy": None, "properties": {}})
        merged["apis"] = sorted(set(merged.get("apis") or []) | set(product.get("apis") or []))
        merged["policy"] = merged.get("policy") or product.get("policy")
        merged["properties"] = product.get("properties") or merged.get("properties") or {}
    target.backends.update(source.backends)
    target.named_values = sorted(set(target.named_values) | set(source.named_values))
    target.version_sets.update(source.version_sets)
    target.global_policy = target.global_policy or source.global_policy
    target.linked_policies.extend(source.linked_policies)


def _estate_policies(estate: ArmEstate) -> List[ScopedPolicy]:
    """The policy documents an ARM estate carries, as scoped policies."""
    found: List[ScopedPolicy] = []
    if estate.global_policy:
        found.append(ScopedPolicy("global", read_policy_xml(estate.global_policy)))
    for name, product in sorted(estate.products.items()):
        if product.get("policy"):
            found.append(ScopedPolicy("product", read_policy_xml(product["policy"]), name=name))
    for api in estate.apis:
        if api.policy:
            found.append(ScopedPolicy("api", read_policy_xml(api.policy), name=api.name))
        for op_name, xml in sorted(api.operation_policies.items()):
            found.append(ScopedPolicy("operation", read_policy_xml(xml), api=api.name, operation=op_name))
    return found


def _definition_operations(document: Mapping[str, Any]) -> List[Tuple[str, str, Mapping[str, Any]]]:
    paths = document.get("paths") if isinstance(document.get("paths"), Mapping) else {}
    return [
        (str(path), method, item[method])
        for path, item in paths.items()
        if isinstance(item, Mapping)
        for method in _HTTP_METHODS
        if isinstance(item.get(method), Mapping)
    ]


def _check_references(native: Mapping[str, Any]) -> None:
    """Reject undeclared named values, and backend ids the input's declared backends lack."""
    estate = ArmEstate()
    templates = ([native["template"]] if native.get("kind") == "arm" else []) + list(native.get("arm") or [])
    for template in templates:
        _merge_estate(estate, read_arm_template(template))
    texts = [str(m.get("xml") or "") for m in native.get("policies") or []]
    texts += [estate.global_policy or ""] + [p.get("policy") or "" for p in estate.products.values()]
    for api in estate.apis:
        texts += [api.policy or ""] + list(api.operation_policies.values())
    declared = set(estate.named_values)
    missing = sorted({name for text in texts for name in named_value_references(text)} - declared)
    if missing:
        raise ImportSourceError(
            "Policy refers to named value(s) the input does not declare: "
            + ", ".join(f"{{{{{n}}}}}" for n in missing)
            + ". Include the Microsoft.ApiManagement/service/namedValues resources (names only).",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    if estate.backends:
        ids = set()
        for text in texts:
            if text.strip():
                root = read_policy_xml(text)
                ids.update(
                    el.get("backend-id")
                    for el in root.iter()
                    if isinstance(el.tag, str)
                    and el.tag.rsplit("}", 1)[-1] == "set-backend-service"
                    and el.get("backend-id")
                )
        unknown = sorted(ids - set(estate.backends))
        if unknown:
            raise ImportSourceError(
                "set-backend-service names backend id(s) the input does not declare: " + ", ".join(unknown),
                code="INPUT_REFERENCE_UNRESOLVED",
            )


# ---------------------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------------------


def _definition_security(op: Mapping[str, Any], document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The definition's own security requirement for one operation, as canonical records."""
    components = document.get("components") if isinstance(document.get("components"), Mapping) else {}
    schemes = components.get("securitySchemes") or document.get("securityDefinitions") or {}
    records: List[Dict[str, Any]] = []
    for requirement in op.get("security", document.get("security")) or []:
        if not isinstance(requirement, Mapping):
            continue
        for name, scopes in requirement.items():
            scheme = schemes.get(str(name)) if isinstance(schemes, Mapping) else None
            if isinstance(scheme, Mapping):
                records.append(
                    {**security_for_scheme(str(name), scheme, list(scopes or [])), "derivedFrom": "definition"}
                )
    records.sort(key=lambda r: (r["name"], r["scheme"]))
    return records


def _pick(policies: Sequence[ScopedPolicy], scope: str, **match: Optional[str]) -> List[ScopedPolicy]:
    out = []
    for policy in policies:
        if policy.scope != scope:
            continue
        if all(value is None or getattr(policy, key) in (None, value) for key, value in match.items()):
            out.append(policy)
    return out


def _api_pipeline(ctx: _Context, api_name: Optional[str]):
    """The composed pipeline for one API: global → (single) product → API, and what it inherits."""
    unresolved: List[str] = []
    parent = None
    global_doc = next(iter(_pick(ctx.policies, "global")), None)
    if global_doc is not None:
        parent, missing = compose(global_doc, None)
        unresolved += missing
    linked = {name for name, p in ctx.estate.products.items() if api_name in (p.get("apis") or [])}
    products = [p for p in _pick(ctx.policies, "product") if not linked or p.name in linked]
    if len(products) == 1:
        parent, missing = compose(products[0], parent)
        unresolved = missing if parent is None else unresolved
    api_docs = _pick(ctx.policies, "api", name=api_name)
    api_doc = api_docs[0] if api_docs else None
    if api_doc is None:
        return parent, unresolved, None
    pipeline, missing = compose(api_doc, parent)
    return pipeline, (missing if parent is None else unresolved), api_doc


def _scope_set(facts: PolicyFacts) -> List[str]:
    scopes = {m["scope"] for m in facts.mapped} | {u["scope"] for u in facts.unmapped}
    return sorted(scopes, key=lambda s: _SCOPE_ORDER.get(s, 9))


def _write_facts(target: Dict[str, Any], facts: PolicyFacts, definition_backend: Optional[Dict[str, Any]]) -> None:
    """Write policy facts into an extras bag under the canonical keys."""
    if facts.security:
        target["security"] = list(target.get("security") or []) + facts.security
    if facts.rate_limits:
        target["rate_limits"] = facts.rate_limits
    backend = facts.backend or definition_backend
    if backend:
        target["backend"] = backend
    if facts.rewrite:
        target["rewrite"] = facts.rewrite
    if facts.cors:
        target["cors"] = facts.cors
    if facts.access:
        target["access"] = facts.access


def _interpret(model: CanonicalApi, ctx: _Context) -> None:
    """Compose and interpret every policy onto ``model`` (in place) and write the APIM report."""
    backends = ctx.estate.backends
    ops: Dict[str, Operation] = {op.key: op for op in model.operations()}
    api_names = sorted({owner[0] for owner in ctx.owners.values() if owner[0]}) or [None]
    api_props = {api.name: api.properties for api in ctx.estate.apis}
    unmapped: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    mapped_counts: Dict[str, Dict[str, Any]] = {}
    unresolved_backends: set = set()
    attached: set = set()
    api_facts_by_name: Dict[Optional[str], PolicyFacts] = {}

    def _record(facts: PolicyFacts, operation: Optional[str]) -> None:
        for entry in facts.unmapped:
            op_label = operation if entry["scope"] == "operation" else None
            key = (entry["scope"], op_label, entry["section"], entry["name"], entry["xml"])
            unmapped.setdefault(key, {**entry, **({"operation": op_label} if op_label else {})})
        for entry in facts.mapped:
            bucket = mapped_counts.setdefault(entry["policy"], {"count": 0, "scopes": set()})
            bucket["scopes"].add(entry["scope"])
        unresolved_backends.update(b for b in facts.backend_ids if b not in backends)

    for api_name in api_names:
        pipeline, inherits, _api_doc = _api_pipeline(ctx, api_name)
        api_facts = interpret(pipeline or {}, backends=backends, unresolved=inherits)
        api_facts_by_name[api_name] = api_facts
        _record(api_facts, None)

    # Mapped counts per element, not per operation: count each scope's own elements once.
    for policy in ctx.policies:
        own, _ = compose(policy, None)
        for entry in interpret(own, backends=backends).mapped:
            mapped_counts.setdefault(entry["policy"], {"count": 0, "scopes": set()})["count"] += 1

    definition = ctx.definition or {}
    for path, method, op_obj in _definition_operations(definition):
        operation = ops.get(Keys.operation_http(method, path))
        if operation is None:
            continue
        api_name, op_name = ctx.owners.get((method.upper(), path), (None, op_obj.get("operationId")))
        api_key = api_name if api_name in api_facts_by_name else api_names[0]
        security = _definition_security(op_obj, definition)
        if security:
            operation.extras["security"] = security
        definition_backend = _definition_backend(api_props.get(api_name) if api_name else _single_props(ctx))
        op_docs = _pick(ctx.policies, "operation", api=api_name, operation=op_name) if op_name else []
        if op_docs:
            attached.add((api_name, op_name))
            parent, inherits, api_doc = _api_pipeline(ctx, api_name)
            pipeline, missing = compose(op_docs[0], parent)
            facts = interpret(pipeline, backends=backends, unresolved=missing if parent is None else inherits)
            _record(facts, op_name)
            own_unmapped = [u for u in facts.unmapped if u["scope"] == "operation"]
            if own_unmapped:
                operation.extras[APIM_EXTRAS_KEY] = {"unmapped": own_unmapped}
        else:
            facts = api_facts_by_name.get(api_key) or PolicyFacts()
        _write_facts(operation.extras, facts, definition_backend)
        scopes = _scope_set(facts)
        if scopes:
            operation.extras.setdefault(APIM_EXTRAS_KEY, {})["policyScopes"] = scopes

    # API-scope facts on the API itself (policy documents without a definition included).
    primary = api_facts_by_name.get(api_names[0]) or PolicyFacts()
    if primary.cors:
        model.extras["cors"] = primary.cors
    if primary.rate_limits:
        model.extras["rate_limits"] = primary.rate_limits
    if primary.access:
        model.extras["access"] = primary.access
    backend_url = (primary.backend or {}).get("uri") or (_definition_backend(_single_props(ctx)) or {}).get("uri")
    if backend_url and all(server.url != backend_url for server in model.servers):
        model.servers.append(
            Server(url=backend_url, name="backend", description="Backend service the APIM gateway forwards to.")
        )

    unattached = sorted(
        {
            f"{p.api + '/' if p.api else ''}{p.operation}"
            for p in ctx.policies
            if p.scope == "operation" and (p.api, p.operation) not in attached and (None, p.operation) not in attached
        }
    )
    unattached_facts: Dict[str, Any] = {}
    for label in unattached:
        api_name, _, op_name = label.rpartition("/")
        doc = _pick(ctx.policies, "operation", api=api_name or None, operation=op_name)[0]
        parent, inherits, _ = _api_pipeline(ctx, api_name or None)
        pipeline, missing = compose(doc, parent)
        facts = interpret(pipeline, backends=backends, unresolved=missing if parent is None else inherits)
        _record(facts, op_name)
        bag: Dict[str, Any] = {}
        _write_facts(bag, facts, None)
        unattached_facts[label] = bag

    model.extras[APIM_EXTRAS_KEY] = {
        "provenance": "declared",
        "shape": ctx.shape,
        "service": ctx.estate.service,
        "apis": [_api_summary(api.name, api.properties, len(api.operations)) for api in ctx.estate.apis],
        "versionSets": [
            {"name": name, "displayName": props.get("displayName"), "versioningScheme": props.get("versioningScheme")}
            for name, props in sorted(ctx.estate.version_sets.items())
        ],
        "products": [
            {
                "name": name,
                "displayName": (p.get("properties") or {}).get("displayName"),
                "subscriptionRequired": (p.get("properties") or {}).get("subscriptionRequired"),
                "approvalRequired": (p.get("properties") or {}).get("approvalRequired"),
                "state": (p.get("properties") or {}).get("state"),
                "apis": sorted(p.get("apis") or []),
            }
            for name, p in sorted(ctx.estate.products.items())
        ],
        "backends": [{"id": k, **v} for k, v in sorted(backends.items())],
        "namedValues": list(ctx.estate.named_values),
        "policies": sorted(
            (_policy_summary(p) for p in ctx.policies),
            key=lambda s: (
                _SCOPE_ORDER.get(s["scope"], 9),
                s.get("name") or "",
                s.get("api") or "",
                s.get("operation") or "",
            ),
        ),
        "apiPolicy": _facts_summary(primary),
        "unattachedOperations": unattached_facts,
        "mapped": {
            name: {"count": v["count"], "scopes": sorted(v["scopes"], key=lambda s: _SCOPE_ORDER.get(s, 9))}
            for name, v in sorted(mapped_counts.items())
        },
        "unmapped": sorted(
            unmapped.values(),
            key=lambda u: (
                _SCOPE_ORDER.get(u["scope"], 9),
                u.get("operation") or "",
                u["section"],
                u["name"],
                u["xml"],
            ),
        ),
        "unresolvedBackends": sorted(unresolved_backends),
        "linkedPolicies": list(ctx.estate.linked_policies),
        "collisions": list(ctx.collisions),
    }


def _single_props(ctx: _Context) -> Optional[Dict[str, Any]]:
    return ctx.estate.apis[0].properties if len(ctx.estate.apis) == 1 else None


def _definition_backend(props: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not props or not props.get("serviceUrl"):
        return None
    return {"kind": "http", "uri": props["serviceUrl"], "provenance": "declared", "derivedFrom": "definition"}


def _api_summary(name: str, props: Mapping[str, Any], operation_count: int) -> Dict[str, Any]:
    keys = (
        "displayName",
        "path",
        "apiVersion",
        "apiVersionSetId",
        "apiRevision",
        "isCurrent",
        "apiType",
        "serviceUrl",
        "subscriptionRequired",
        "protocols",
    )
    return {"name": name, **{k: props[k] for k in keys if k in props}, "operationCount": operation_count}


def _policy_summary(policy: ScopedPolicy) -> Dict[str, Any]:
    sections = {}
    for section_el in policy.root:
        if isinstance(section_el.tag, str):
            sections[section_el.tag.rsplit("}", 1)[-1]] = [
                el.tag.rsplit("}", 1)[-1] for el in section_el if isinstance(el.tag, str)
            ]
    summary: Dict[str, Any] = {"scope": policy.scope, "sections": sections}
    for key in ("name", "api", "operation"):
        if getattr(policy, key):
            summary[key] = getattr(policy, key)
    return summary


def _facts_summary(facts: PolicyFacts) -> Dict[str, Any]:
    bag: Dict[str, Any] = {}
    _write_facts(bag, facts, None)
    if facts.inherits:
        bag["inheritsFromParentScope"] = list(facts.inherits)
    return bag
