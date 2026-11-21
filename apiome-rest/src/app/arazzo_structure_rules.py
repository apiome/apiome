"""Arazzo 1.1 structural validation rules — GVM-4.4 (#5879).

The checks behind the twelve ``arazzo.*`` rules :class:`app.arazzo_lint.ArazzoRulePack` added
for workflow authors: runtime-expression grammar, success-criteria context, ``goto`` targets,
``$components`` references, duplicate ids, ``dependsOn`` cycles, parameter locations, input
schemas, output expressions and source-description types. Each check is a pure function of the
normalized :class:`~app.canonical_model.CanonicalApi` (:mod:`app.arazzo_normalizer`) yielding
``(path, message)`` pairs, the shape :class:`~app.lint_engine.LintRule` expects.

Where the data lives in the model:

* each workflow is a :class:`~app.canonical_model.Service` whose ``extras`` carry ``inputs``,
  ``parameters``, ``outputs``, ``dependsOn``, ``successActions`` and ``failureActions``;
* each step is an :class:`~app.canonical_model.Operation` whose ``extras`` carry ``stepId``,
  ``parameters``, ``requestBody``, ``successCriteria``, ``onSuccess``, ``onFailure``,
  ``outputs``, the step target fields and the derived ``sourceType`` / ``asyncStep``;
* the document's ``components``, ``sourceDescriptions`` and ``arazzo`` marker sit on the root
  ``extras``.

Checks never guess: a value of the wrong shape is skipped rather than reported by a rule that
is about something else, so each rule fires only for its own defect.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from .arazzo_expression_grammar import (
    ExpressionIssue,
    condition_expression_errors,
    is_whole_expression,
    runtime_expression_error,
    string_expression_errors,
)
from .arazzo_spec import (
    SOURCE_TYPE_ASYNCAPI,
    SOURCE_TYPE_OPENAPI,
    ArazzoVersionError,
    allowed_source_types,
    parameter_locations,
    parse_arazzo_version,
    resolve_step_target,
    source_description_names,
    supports_async_sources,
)
from .canonical_model import CanonicalApi, Operation, Service

__all__ = [
    "check_component_ref_unresolved",
    "check_depends_on_cycle",
    "check_inputs_schema_invalid",
    "check_on_failure_target_unresolved",
    "check_on_success_target_unresolved",
    "check_outputs_expression_invalid",
    "check_parameter_in_invalid",
    "check_runtime_expression_invalid",
    "check_source_description_type_invalid",
    "check_step_id_duplicate",
    "check_success_criteria_context_required",
    "check_workflow_id_duplicate",
]

Finding = Tuple[str, str]

#: Criterion types whose condition is a query over a value, so ``context`` names that value.
_CONTEXT_TYPES = ("jsonpath", "regex")

#: ``$components.<kind>[.<name>]`` anywhere in a string; ``name`` stops where an expression would.
_COMPONENT_REF = re.compile(r"\$components\.([A-Za-z0-9_\-]+)(?:\.([^\s{}#=!<>&|()'\"]+))?")

#: ``$sourceDescriptions.<name>.<workflowId>`` — a ``goto`` / ``dependsOn`` into another document.
_SOURCE_WORKFLOW = re.compile(r"^\$sourceDescriptions\.(?P<source>[A-Za-z0-9_-]+)\.(?P<id>.+)$")


# =============================================================================================
# Model traversal helpers
# =============================================================================================


def _workflows(api: CanonicalApi) -> List[Service]:
    """Workflows in key order (the model is already sorted; sorting again keeps this pure)."""
    return sorted(api.services, key=lambda s: s.key)


def _steps(service: Service) -> List[Operation]:
    """A workflow's steps in key order."""
    return sorted(service.operations, key=lambda o: o.key)


def _workflow_path(service: Service) -> str:
    return f"services.{service.key}"


def _step_path(service: Service, operation: Operation) -> str:
    return f"services.{service.key}.operations.{operation.key}"


def _step_id(operation: Operation) -> str:
    """The step's id as the document spells it (the normalizer's fallback otherwise)."""
    step_id = operation.extras.get("stepId")
    return step_id if isinstance(step_id, str) else operation.name


def _components(api: CanonicalApi) -> Dict[str, Any]:
    components = api.extras.get("components")
    return components if isinstance(components, dict) else {}


def _component_group(api: CanonicalApi, kind: str) -> Dict[str, Any]:
    group = _components(api).get(kind)
    return group if isinstance(group, dict) else {}


def _dicts(value: Any) -> List[Dict[str, Any]]:
    """The mapping entries of a list (anything else yields nothing)."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _is_reference(entry: Mapping[str, Any]) -> bool:
    """Whether an entry points at a reusable component instead of spelling one out — the Arazzo
    Reusable Object (``reference: $components.…``) or a JSON Reference (``$ref: '#/components/…'``)."""
    return "reference" in entry or "$ref" in entry


def _criterion_kind(criterion: Mapping[str, Any]) -> str:
    """A criterion's type — a string, or the ``type`` of an expression-type object."""
    declared = criterion.get("type")
    if isinstance(declared, Mapping):
        declared = declared.get("type")
    return str(declared or "simple").strip().lower() or "simple"


def _iter_strings(value: Any) -> Iterator[str]:
    """Every string nested anywhere inside ``value``."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_strings(nested)


def _issues_text(issues: Sequence[ExpressionIssue]) -> str:
    return "; ".join(issue.describe() for issue in issues)


# Each "site" below is (path, label, value): where a thing lives, how a message names it, and
# the raw value — so the checks share one walk over criteria and actions.


def _step_action_lists(operation: Operation) -> List[Tuple[str, Any]]:
    return [("onSuccess", operation.extras.get("onSuccess")), ("onFailure", operation.extras.get("onFailure"))]


def _criteria_sites(api: CanonicalApi) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """Every success criterion in the document: step criteria and every action's ``criteria``."""
    for service in _workflows(api):
        for operation in _steps(service):
            path = _step_path(service, operation)
            for index, criterion in enumerate(_dicts(operation.extras.get("successCriteria"))):
                yield path, f"successCriteria[{index}]", criterion
            for field, actions in _step_action_lists(operation):
                for a_index, action in enumerate(_dicts(actions)):
                    for c_index, criterion in enumerate(_dicts(action.get("criteria"))):
                        yield path, f"{field}[{a_index}].criteria[{c_index}]", criterion
        for field in ("successActions", "failureActions"):
            for a_index, action in enumerate(_dicts(service.extras.get(field))):
                for c_index, criterion in enumerate(_dicts(action.get("criteria"))):
                    yield _workflow_path(service), f"{field}[{a_index}].criteria[{c_index}]", criterion
    for field in ("successActions", "failureActions"):
        for name, action in sorted(_component_group(api, field).items()):
            if not isinstance(action, dict):
                continue
            for c_index, criterion in enumerate(_dicts(action.get("criteria"))):
                yield f"components.{field}.{name}", f"criteria[{c_index}]", criterion


# =============================================================================================
# arazzo.runtime-expression-invalid
# =============================================================================================


def _criterion_expression_issues(criterion: Mapping[str, Any]) -> List[Tuple[str, List[ExpressionIssue]]]:
    """Grammar issues in a criterion's ``context`` and (for ``simple``) its ``condition``."""
    found: List[Tuple[str, List[ExpressionIssue]]] = []
    context = criterion.get("context")
    if isinstance(context, str) and context.strip():
        issue = runtime_expression_error(context)
        if issue is not None:
            found.append(("context", [issue]))
    condition = criterion.get("condition")
    if isinstance(condition, str) and _criterion_kind(criterion) == "simple":
        issues = condition_expression_errors(condition)
        if issues:
            found.append(("condition", issues))
    return found


def _is_selector(value: Any) -> bool:
    """Whether ``value`` is an Arazzo 1.1 Selector Object (``{context, selector, type}``)."""
    return isinstance(value, dict) and "context" in value and "selector" in value


def _value_issues(value: Any) -> List[ExpressionIssue]:
    """Grammar issues in a parameter value or request body, member by member.

    A 1.1 Selector Object contributes its ``context`` (which must be a whole runtime expression);
    its ``selector`` is a JSONPath / XPath / JSON Pointer query, not a runtime expression.
    """
    if _is_selector(value):
        context = value.get("context")
        if not isinstance(context, str):
            return []
        issue = runtime_expression_error(context)
        return [] if issue is None else [issue]
    if isinstance(value, dict):
        return [issue for nested in value.values() for issue in _value_issues(nested)]
    if isinstance(value, list):
        return [issue for nested in value for issue in _value_issues(nested)]
    if isinstance(value, str):
        return string_expression_errors(value)
    return []


def _parameter_sites(api: CanonicalApi) -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """Every parameter entry: steps, workflows and ``components.parameters``."""
    for service in _workflows(api):
        for index, parameter in enumerate(_dicts(service.extras.get("parameters"))):
            yield _workflow_path(service), f"parameters[{index}]", parameter
        for operation in _steps(service):
            for index, parameter in enumerate(_dicts(operation.extras.get("parameters"))):
                yield _step_path(service, operation), f"parameters[{index}]", parameter
    for name, parameter in sorted(_component_group(api, "parameters").items()):
        if isinstance(parameter, dict):
            yield f"components.parameters.{name}", "parameter", parameter


def check_runtime_expression_invalid(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a ``$``-expression that does not parse against the Arazzo runtime-expression grammar.

    Checked: parameter values, request bodies, criterion ``context`` and ``simple`` conditions
    (steps, actions, workflows, components). Outputs are left to
    ``arazzo.outputs-expression-invalid``, so one malformed output is reported once; ``jsonpath``
    and ``regex`` conditions are queries, not runtime expressions, and are not parsed.
    """
    for path, label, parameter in _parameter_sites(api):
        if "value" in parameter:
            issues = _value_issues(parameter.get("value"))
            if issues:
                yield path, f"{label}.value has an invalid runtime expression: {_issues_text(issues)}."
    for service in _workflows(api):
        for operation in _steps(service):
            issues = _value_issues(operation.extras.get("requestBody"))
            if issues:
                yield (
                    _step_path(service, operation),
                    f"requestBody has an invalid runtime expression: {_issues_text(issues)}.",
                )
    for path, label, criterion in _criteria_sites(api):
        for part, issues in _criterion_expression_issues(criterion):
            yield path, f"{label}.{part} has an invalid runtime expression: {_issues_text(issues)}."


# =============================================================================================
# arazzo.success-criteria-context-required
# =============================================================================================


def check_success_criteria_context_required(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a ``jsonpath`` or ``regex`` criterion that declares no ``context``.

    Such a condition is a query over a value; without ``context`` (for example
    ``$response.body``) a runner has nothing to apply it to.
    """
    for path, label, criterion in _criteria_sites(api):
        kind = _criterion_kind(criterion)
        if kind not in _CONTEXT_TYPES:
            continue
        context = criterion.get("context")
        if isinstance(context, str) and context.strip():
            continue
        yield (
            path,
            f"{label} is a {kind} criterion with no context; name the value it applies to "
            "(for example `context: $response.body`).",
        )


# =============================================================================================
# arazzo.on-success-target-unresolved / arazzo.on-failure-target-unresolved
# =============================================================================================


def _goto_target_error(
    action: Mapping[str, Any],
    *,
    step_ids: Set[str],
    workflow_ids: Set[str],
    source_names: Set[str],
) -> Optional[str]:
    """Why a ``goto`` action's target does not resolve, or ``None`` when it does (or is no goto)."""
    if _is_reference(action):
        return None  # a reusable-action reference; resolved where the component is defined
    step_id = action.get("stepId")
    workflow_id = action.get("workflowId")
    kind = str(action.get("type") or "").strip().lower()
    if step_id is None and workflow_id is None:
        if kind == "goto":
            return "is a goto that names neither a stepId nor a workflowId"
        return None
    if isinstance(step_id, str) and step_id.strip():
        if step_id not in step_ids:
            return f"targets stepId {step_id!r}, which is not a step of this workflow"
    elif step_id is not None:
        return "has a stepId that is not a non-empty string"
    if isinstance(workflow_id, str) and workflow_id.strip():
        match = _SOURCE_WORKFLOW.match(workflow_id.strip())
        if match is not None:
            if match.group("source") not in source_names:
                return (
                    f"targets workflow {workflow_id!r} in sourceDescription "
                    f"{match.group('source')!r}, which is not declared"
                )
        elif workflow_id not in workflow_ids:
            return f"targets workflowId {workflow_id!r}, which no workflow of this document declares"
    elif workflow_id is not None:
        return "has a workflowId that is not a non-empty string"
    return None


def _action_target_findings(
    api: CanonicalApi, step_field: str, workflow_field: str, component_field: str
) -> Iterator[Finding]:
    """``goto`` target findings for one action family (success or failure)."""
    services = _workflows(api)
    workflow_ids = {service.key for service in services}
    all_step_ids = {_step_id(op) for service in services for op in service.operations}
    source_names = {name for name in source_description_names(api.extras.get("sourceDescriptions")) if name}

    def _check(path: str, label: str, actions: Any, step_ids: Set[str]) -> Iterator[Finding]:
        for index, action in enumerate(_dicts(actions)):
            error = _goto_target_error(action, step_ids=step_ids, workflow_ids=workflow_ids, source_names=source_names)
            if error is not None:
                yield path, f"{label}[{index}] {error}."

    for service in services:
        step_ids = {_step_id(op) for op in service.operations}
        for operation in _steps(service):
            yield from _check(_step_path(service, operation), step_field, operation.extras.get(step_field), step_ids)
        yield from _check(_workflow_path(service), workflow_field, service.extras.get(workflow_field), step_ids)
    # A reusable action is not bound to one workflow, so its stepId may name a step of any.
    for name, action in sorted(_component_group(api, component_field).items()):
        if isinstance(action, dict):
            yield from _check(f"components.{component_field}.{name}", "action", [action], all_step_ids)


def check_on_success_target_unresolved(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a success action whose ``goto`` target (``stepId`` / ``workflowId``) does not resolve.

    Covers step ``onSuccess``, workflow ``successActions`` and ``components.successActions``. A
    ``stepId`` must name a step of the same workflow; a ``workflowId`` a workflow of this
    document, or ``$sourceDescriptions.<name>.<workflowId>`` with a declared source.
    """
    return _action_target_findings(api, "onSuccess", "successActions", "successActions")


def check_on_failure_target_unresolved(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a failure action whose ``goto`` target does not resolve (the failure twin of
    :func:`check_on_success_target_unresolved`: step ``onFailure``, workflow ``failureActions``,
    ``components.failureActions``)."""
    return _action_target_findings(api, "onFailure", "failureActions", "failureActions")


# =============================================================================================
# arazzo.component-ref-unresolved
# =============================================================================================


def _component_reference_errors(api: CanonicalApi, text: str) -> List[str]:
    """Every ``$components.*`` reference in ``text`` that the document does not declare."""
    errors: List[str] = []
    components = _components(api)
    for match in _COMPONENT_REF.finditer(text):
        kind, name = match.group(1), match.group(2)
        group = components.get(kind)
        reference = match.group(0)
        if not isinstance(group, dict):
            errors.append(f"{reference!r} names components.{kind}, which the document does not declare")
            continue
        if not name:
            errors.append(f"{reference!r} names no entry of components.{kind}")
            continue
        if name not in group and name.split(".")[0] not in group:
            errors.append(f"{reference!r} names no entry of components.{kind}")
    return errors


def check_component_ref_unresolved(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a ``$components.<kind>.<name>`` reference the document's ``components`` lack.

    Scans every step and workflow field that may hold an expression or a reusable-object
    ``reference`` (parameters, request bodies, criteria, actions, outputs, inputs) and the
    components themselves, which may reference one another.
    """
    step_fields = ("parameters", "requestBody", "successCriteria", "onSuccess", "onFailure", "outputs")
    workflow_fields = ("parameters", "inputs", "outputs", "successActions", "failureActions")

    def _errors(value: Any) -> List[str]:
        found: List[str] = []
        for text in _iter_strings(value):
            if "$components" in text:
                found.extend(_component_reference_errors(api, text))
        return sorted(set(found))

    for service in _workflows(api):
        for operation in _steps(service):
            for field in step_fields:
                for error in _errors(operation.extras.get(field)):
                    yield _step_path(service, operation), f"{field}: {error}."
        for field in workflow_fields:
            for error in _errors(service.extras.get(field)):
                yield _workflow_path(service), f"{field}: {error}."
    for kind, group in sorted(_components(api).items()):
        for error in _errors(group):
            yield f"components.{kind}", f"{error}."


# =============================================================================================
# arazzo.step-id-duplicate / arazzo.workflow-id-duplicate
# =============================================================================================


def _duplicates(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    repeated: Set[str] = set()
    for value in values:
        (repeated if value in seen else seen).add(value)
    return sorted(repeated)


def check_step_id_duplicate(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a ``stepId`` declared more than once in the same workflow.

    ``$steps.<stepId>`` expressions and ``goto`` actions address steps by id, so a repeated id
    makes them ambiguous.
    """
    for service in _workflows(api):
        for step_id in _duplicates(_step_id(op) for op in service.operations):
            yield _workflow_path(service), f"stepId {step_id!r} is declared more than once in this workflow."


def check_workflow_id_duplicate(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a ``workflowId`` declared by more than one workflow of the document."""
    for workflow_id in _duplicates(service.key for service in api.services):
        yield f"services.{workflow_id}", f"workflowId {workflow_id!r} is declared by more than one workflow."


# =============================================================================================
# arazzo.depends-on-cycle
# =============================================================================================


def _local_dependencies(service: Service, workflow_ids: Set[str]) -> List[str]:
    """The workflows of this document a workflow's ``dependsOn`` names (others are skipped)."""
    depends = service.extras.get("dependsOn")
    if not isinstance(depends, list):
        return []
    return sorted({item for item in depends if isinstance(item, str) and item in workflow_ids})


def _strongly_connected(graph: Mapping[str, Sequence[str]]) -> List[List[str]]:
    """Tarjan's strongly connected components of ``graph``, each sorted, in sorted order."""
    index: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: Set[str] = set()
    components: List[List[str]] = []

    def _connect(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for target in graph.get(node, ()):
            if target not in index:
                _connect(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component: List[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            components.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            _connect(node)
    return sorted(components)


def _shortest_cycle(graph: Mapping[str, Sequence[str]], start: str, members: Set[str]) -> List[str]:
    """The shortest ``dependsOn`` path from ``start`` back to itself, staying inside ``members``."""
    previous: Dict[str, str] = {}
    frontier = [start]
    while frontier:
        following: List[str] = []
        for node in frontier:
            for target in graph.get(node, ()):
                if target not in members:
                    continue
                if target == start:
                    path = [node]
                    while path[-1] != start:
                        path.append(previous[path[-1]])
                    return list(reversed(path))
                if target not in previous:
                    previous[target] = node
                    following.append(target)
        frontier = following
    return [start]  # pragma: no cover - every reported component holds a cycle through start


def check_depends_on_cycle(api: CanonicalApi) -> Iterable[Finding]:
    """Flag workflows whose ``dependsOn`` chain leads back to themselves.

    Each group of mutually dependent workflows (a strongly connected component, or a workflow
    that depends on itself) is reported once, at its alphabetically first workflow, with the
    shortest chain through it spelled out (``a → b → a``). Dependencies on other documents
    (``$sourceDescriptions.<name>.<workflowId>``) cannot close a local cycle and are ignored.
    Runs in time linear in the number of workflows and dependencies.
    """
    workflow_ids = {service.key for service in api.services}
    graph: Dict[str, List[str]] = {}
    for service in _workflows(api):
        merged = set(graph.get(service.key, ())) | set(_local_dependencies(service, workflow_ids))
        graph[service.key] = sorted(merged)

    for component in _strongly_connected(graph):
        start = component[0]
        if len(component) == 1 and start not in graph.get(start, ()):
            continue
        cycle = _shortest_cycle(graph, start, set(component))
        chain = " → ".join(cycle + [start])
        yield f"services.{start}", f"dependsOn forms a cycle: {chain}."


# =============================================================================================
# arazzo.parameter-in-invalid
# =============================================================================================


def _step_source_type(api: CanonicalApi, operation: Operation) -> Optional[str]:
    """The kind of source a step calls: ``openapi``, ``asyncapi``, or ``None`` (a workflow call,
    or a source whose type sets no parameter locations)."""
    names = source_description_names(api.extras.get("sourceDescriptions"))
    target = resolve_step_target(operation.extras, source_names=names)
    if target is None or target.kind == "workflowId":
        return None
    if operation.extras.get("asyncStep") or operation.extras.get("sourceType") == SOURCE_TYPE_ASYNCAPI:
        return SOURCE_TYPE_ASYNCAPI
    source_type = operation.extras.get("sourceType")
    if source_type in (None, SOURCE_TYPE_OPENAPI):
        return SOURCE_TYPE_OPENAPI
    return None


def check_parameter_in_invalid(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a step parameter whose ``in`` is missing or not a location its source type defines.

    An operation step must say where each parameter goes. Under Arazzo 1.0 an OpenAPI step may
    use ``path``, ``query``, ``header`` or ``cookie``; 1.1 adds ``querystring``, and an AsyncAPI
    step may use ``header`` or ``channel`` (:func:`app.arazzo_spec.parameter_locations`). A step
    that calls a workflow maps parameters onto that workflow's inputs, so it has no ``in`` to
    check; reusable ``reference`` / ``$ref`` entries are checked where they are defined; an AsyncAPI step
    under 1.0 is ``arazzo.async-source-before-1-1``'s finding, not this rule's.
    """
    try:
        version = parse_arazzo_version(api.extras.get("arazzo"))
    except ArazzoVersionError:
        return
    for service in _workflows(api):
        for operation in _steps(service):
            source_type = _step_source_type(api, operation)
            allowed = parameter_locations(version, source_type) if source_type else ()
            if not allowed:
                continue
            for index, parameter in enumerate(_dicts(operation.extras.get("parameters"))):
                if _is_reference(parameter):
                    continue
                name = parameter.get("name")
                label = f"parameters[{index}]" + (f" ({name!r})" if isinstance(name, str) else "")
                location = parameter.get("in")
                if location is None:
                    yield (
                        _step_path(service, operation),
                        f"{label} declares no `in`; an {source_type} step must say where it "
                        f"goes ({', '.join(allowed)}).",
                    )
                elif location not in allowed:
                    yield (
                        _step_path(service, operation),
                        f"{label} has `in: {location}`, which an {source_type} step under Arazzo "
                        f"{api.extras.get('arazzo')} does not define (expected one of "
                        f"{', '.join(allowed)}).",
                    )


# =============================================================================================
# arazzo.inputs-schema-invalid
# =============================================================================================


def _schema_error(schema: Any) -> Optional[str]:
    """Why ``schema`` is not a valid JSON Schema 2020-12 document, or ``None`` when it is."""
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    if not isinstance(schema, (dict, bool)):
        return "is not a JSON Schema object"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        location = "/".join(str(part) for part in exc.path)
        where = f" at /{location}" if location else ""
        return f"is not a valid JSON Schema 2020-12 schema{where}: {exc.message}"
    return None


def check_inputs_schema_invalid(api: CanonicalApi) -> Iterable[Finding]:
    """Flag workflow ``inputs`` (or a ``components.inputs`` entry) that is not valid JSON Schema
    2020-12, the dialect Arazzo specifies for inputs."""
    for service in _workflows(api):
        if "inputs" not in service.extras:
            continue
        error = _schema_error(service.extras.get("inputs"))
        if error is not None:
            yield _workflow_path(service), f"inputs {error}."
    for name, schema in sorted(_component_group(api, "inputs").items()):
        error = _schema_error(schema)
        if error is not None:
            yield f"components.inputs.{name}", f"inputs {error}."


# =============================================================================================
# arazzo.outputs-expression-invalid
# =============================================================================================


def _output_error(value: Any, *, selectors_allowed: bool) -> Optional[str]:
    """Why an output value is not a usable runtime expression, or ``None`` when it is.

    Args:
        value: The output value as written.
        selectors_allowed: Whether the document's version (1.1+) admits a Selector Object here.
    """
    if _is_selector(value):
        if not selectors_allowed:
            return "is a selector object, which Arazzo 1.0 does not define (declare `arazzo: 1.1.0`)"
        context = value.get("context")
        if not isinstance(context, str) or not context.strip():
            return "is a selector object whose context is not a runtime expression"
        issue = runtime_expression_error(context)
        return None if issue is None else f"has an invalid selector context: {issue.describe()}"
    if not isinstance(value, str) or not value.strip():
        return "is not a runtime expression string"
    if is_whole_expression(value):
        issue = runtime_expression_error(value)
        return None if issue is None else f"is an invalid runtime expression: {issue.describe()}"
    issues = string_expression_errors(value)
    if issues:
        return f"has an invalid embedded runtime expression: {_issues_text(issues)}"
    if "{$" in value:
        return None  # a template whose embedded expressions all parse
    return f"is the literal {value!r}, not a runtime expression"


def check_outputs_expression_invalid(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a workflow or step output whose value is not a valid runtime expression.

    Outputs are how a workflow hands values on (``$steps.<id>.outputs.<name>``); a literal or a
    malformed expression yields nothing a later step can read. From Arazzo 1.1 an output may
    instead be a Selector Object, whose ``context`` must then be a valid expression.
    """
    try:
        selectors_allowed = parse_arazzo_version(api.extras.get("arazzo")) >= (1, 1)
    except ArazzoVersionError:
        selectors_allowed = True

    def _findings(path: str, outputs: Any) -> Iterator[Finding]:
        if not isinstance(outputs, dict):
            return
        for name, value in sorted(outputs.items()):
            error = _output_error(value, selectors_allowed=selectors_allowed)
            if error is not None:
                yield path, f"outputs.{name} {error}."

    for service in _workflows(api):
        for operation in _steps(service):
            yield from _findings(_step_path(service, operation), operation.extras.get("outputs"))
        yield from _findings(_workflow_path(service), service.extras.get("outputs"))


# =============================================================================================
# arazzo.source-description-type-invalid
# =============================================================================================


def invalid_source_types(api: CanonicalApi) -> List[Tuple[str, str, Tuple[str, ...]]]:
    """Source descriptions whose ``type`` the declared Arazzo version does not define.

    Args:
        api: The normalized Arazzo artifact.

    Returns:
        ``(name, type, allowed types)`` per offending entry, in declaration order; empty when the
        version marker cannot be read (the import would already have rejected it).
    """
    try:
        version = parse_arazzo_version(api.extras.get("arazzo"))
    except ArazzoVersionError:
        return []
    allowed = allowed_source_types(version)
    found: List[Tuple[str, str, Tuple[str, ...]]] = []
    for index, entry in enumerate(_dicts(api.extras.get("sourceDescriptions"))):
        kind = entry.get("type")
        if kind is None:
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) else f"#{index}"
        if not isinstance(kind, str) or kind.strip() not in allowed:
            found.append((name, str(kind), allowed))
    return found


def check_source_description_type_invalid(api: CanonicalApi) -> Iterable[Finding]:
    """Flag a ``sourceDescriptions[].type`` outside the set the declared version allows.

    Arazzo 1.0 defines ``openapi`` and ``arazzo``; 1.1 adds ``asyncapi``. An ``asyncapi``
    source under a 1.0 marker is the one case reported by its own, older rule
    (``arazzo.async-source-before-1-1``), so it is not reported twice.
    """
    try:
        version = parse_arazzo_version(api.extras.get("arazzo"))
    except ArazzoVersionError:
        return
    for name, kind, allowed in invalid_source_types(api):
        if kind == SOURCE_TYPE_ASYNCAPI and not supports_async_sources(version):
            continue
        yield (
            "sourceDescriptions",
            f"Source description {name!r} declares `type: {kind}`, which Arazzo "
            f"{api.extras.get('arazzo')} does not define (expected one of {', '.join(allowed)}).",
        )
