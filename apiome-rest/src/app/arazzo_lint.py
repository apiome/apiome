"""Arazzo lint pack — MFI-30.2 (#4395).

Quality signals for Arazzo workflow documents, layered on the canonical lint engine
(MFI-4.1 :mod:`app.lint_engine`) and the shared scoring formula (MFI-4.2
:mod:`app.schema_lint`). The native :class:`ArazzoRulePack` runs purely over the
:class:`~app.canonical_model.CanonicalApi` produced by :mod:`app.arazzo_normalizer` and
flags:

* **unresolvable operation references** — a step's ``operationId`` is absent from every
  embedded ``sourceDescriptions`` OpenAPI document;
* **unused workflow inputs** — a workflow declares ``inputs`` but no step parameter/body
  references them;
* **missing success criteria** — a step declares no ``successCriteria``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set, Tuple

from .canonical_model import CanonicalApi, Operation, Service
from .lint_engine import LintRule, RulePack, lint_canonical_model
from .schema_lint import LintResult

__all__ = [
    "ArazzoRulePack",
    "collect_embedded_operation_ids",
    "lint_arazzo_result",
    "lint_arazzo",
]

_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

_INPUT_REF = re.compile(r"\$inputs\.([A-Za-z0-9_.-]+)")


def _services_sorted(api: CanonicalApi) -> List[Service]:
    return sorted(api.services, key=lambda s: s.key)


def _operations_sorted(service: Service) -> List[Operation]:
    return sorted(service.operations, key=lambda o: o.key)


def collect_embedded_operation_ids(source_descriptions: Any) -> Set[str]:
    """Return ``operationId`` values declared in embedded OpenAPI/Swagger sources."""
    ids: Set[str] = set()
    if not isinstance(source_descriptions, list):
        return ids
    for entry in source_descriptions:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, dict):
            continue
        if isinstance(content.get("openapi"), str) or isinstance(content.get("swagger"), str):
            ids.update(_operation_ids_from_openapi(content))
    return ids


def _operation_ids_from_openapi(document: Dict[str, Any]) -> Set[str]:
    ids: Set[str] = set()
    for path_item in (document.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and operation_id.strip():
                ids.add(operation_id)
    return ids


def _source_description_names(source_descriptions: Any) -> Set[str]:
    names: Set[str] = set()
    if not isinstance(source_descriptions, list):
        return names
    for entry in source_descriptions:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.add(entry["name"])
    return names


def _iter_steps(api: CanonicalApi) -> Iterable[Tuple[Service, Operation]]:
    for service in _services_sorted(api):
        for operation in _operations_sorted(service):
            yield service, operation


def _step_path(service: Service, operation: Operation) -> str:
    return f"services.{service.key}.operations.{operation.key}"


def _check_dangling_operation_ref(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    known_ids = collect_embedded_operation_ids(api.extras.get("sourceDescriptions"))
    if not known_ids:
        return
    for service, operation in _iter_steps(api):
        operation_id = operation.extras.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            continue
        if operation_id not in known_ids:
            yield (
                _step_path(service, operation),
                f"Step references unknown operationId {operation_id!r}; it is not declared "
                "in any embedded sourceDescription OpenAPI document.",
            )


def _check_unresolvable_operation_ref(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    known_names = _source_description_names(api.extras.get("sourceDescriptions"))
    for service, operation in _iter_steps(api):
        operation_ref = operation.extras.get("operationRef")
        if not isinstance(operation_ref, str) or not operation_ref.strip():
            continue
        if not operation_ref.startswith("#/sourceDescriptions/"):
            yield (
                _step_path(service, operation),
                f"Step operationRef {operation_ref!r} is not a sourceDescriptions pointer.",
            )
            continue
        parts = operation_ref.split("/")
        if len(parts) < 3:
            yield (
                _step_path(service, operation),
                f"Step operationRef {operation_ref!r} is malformed.",
            )
            continue
        source_name = parts[2]
        if known_names and source_name not in known_names:
            yield (
                _step_path(service, operation),
                f"Step operationRef {operation_ref!r} points at unknown sourceDescription "
                f"{source_name!r}.",
            )


def _referenced_input_names(value: Any) -> Set[str]:
    names: Set[str] = set()
    if isinstance(value, str):
        names.update(_INPUT_REF.findall(value))
    elif isinstance(value, dict):
        for nested in value.values():
            names.update(_referenced_input_names(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(_referenced_input_names(nested))
    return names


def _check_unused_workflow_inputs(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for service in _services_sorted(api):
        inputs = service.extras.get("inputs")
        if not isinstance(inputs, dict):
            continue
        properties = inputs.get("properties")
        if not isinstance(properties, dict) or not properties:
            continue
        declared = {name for name in properties if isinstance(name, str)}
        referenced: Set[str] = set()
        for operation in _operations_sorted(service):
            referenced.update(_referenced_input_names(operation.extras.get("parameters")))
            referenced.update(_referenced_input_names(operation.extras.get("requestBody")))
        unused = sorted(declared - referenced)
        if unused:
            yield (
                f"services.{service.key}",
                f"Workflow inputs {', '.join(unused)} are never referenced by any step.",
            )


def _check_missing_success_criteria(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
    for service, operation in _iter_steps(api):
        criteria = operation.extras.get("successCriteria")
        if not criteria:
            yield (
                _step_path(service, operation),
                "Step declares no successCriteria; workflow runners cannot verify completion.",
            )


class ArazzoRulePack(RulePack, register=True):
    """Native hygiene rules for Arazzo workflow artifacts."""

    format = "arazzo"
    pack_id = "arazzo"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="arazzo.dangling-operation-id",
            category="reference",
            severity="error",
            description="Step operationId must resolve to an embedded sourceDescription.",
            check=_check_dangling_operation_ref,
        ),
        LintRule(
            rule_id="arzzo.unresolvable-operation-ref",
            category="reference",
            severity="error",
            description="Step operationRef must point at a declared sourceDescription.",
            check=_check_unresolvable_operation_ref,
        ),
        LintRule(
            rule_id="arazzo.unused-workflow-input",
            category="structure",
            severity="warning",
            description="Workflow inputs should be referenced by at least one step.",
            check=_check_unused_workflow_inputs,
        ),
        LintRule(
            rule_id="arazzo.missing-success-criteria",
            category="structure",
            severity="warning",
            description="Every workflow step should declare successCriteria.",
            check=_check_missing_success_criteria,
        ),
    )

    def rules(self) -> List[LintRule]:
        return list(self._RULES)


def lint_arazzo_result(model: CanonicalApi) -> LintResult:
    """Lint a normalized Arazzo artifact through the shared engine."""
    return lint_canonical_model(model)


def lint_arazzo(raw: str) -> LintResult:
    """Parse, normalize, and lint raw Arazzo source end-to-end."""
    from .arazzo_import_source import ArazzoImportSource

    adapter = ArazzoImportSource()
    native = adapter.parse(raw)
    model = adapter.normalize(native)
    return lint_arazzo_result(model)
