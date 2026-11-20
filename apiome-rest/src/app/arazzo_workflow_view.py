"""Read model for the Arazzo workflow viewer — COA-1.3 (#7039).

REPO-3.4 (#2773) persists an Arazzo import's workflows and steps (``api_workflows`` /
``api_workflow_steps``, V225); this module turns those rows into the payload the UI's
**Workflows** tab renders:

* each workflow with its ``inputs`` / ``outputs`` and ordered steps;
* each step with the target it calls, the internal operation that target resolved to (method,
  route, owning project — so the UI can open it), and the step's success/failure actions;
* each workflow's **source descriptions** with a status: ``resolved`` or ``missing`` from the
  COA-1.2 resolution report recorded on the revision (``format_metadata.arazzoSources``), or
  ``unknown`` when the revision predates that report.

Everything here is pure — no database, no I/O — so the mapping is unit-testable; the routes in
:mod:`app.arazzo_workflow_routes` do the reads and hand the rows in.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .arazzo_workflow_persistence import WorkflowRow, WorkflowStepRow, parse_operation_ref

__all__ = [
    "SOURCE_MISSING",
    "SOURCE_RESOLVED",
    "SOURCE_UNKNOWN",
    "build_source_views",
    "build_workflow_views",
    "step_resolution_counts",
    "step_source_names",
]

#: A source the import resolved (from the fileset, the catalog or a remote fetch).
SOURCE_RESOLVED = "resolved"
#: A source no resolution tier found; its steps cannot be checked or opened.
SOURCE_MISSING = "missing"
#: The revision carries no resolution report (imported before COA-1.2), so the status is not known.
SOURCE_UNKNOWN = "unknown"


def _mapping(value: Any) -> Dict[str, Any]:
    """Return ``value`` when it is a mapping, else an empty dict."""
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return list(value) if isinstance(value, list) else []


def build_source_views(
    source_descriptions: Any, report: Any
) -> List[Dict[str, Any]]:
    """Describe every declared ``sourceDescriptions`` entry and whether it was resolved.

    Args:
        source_descriptions: The document's ``sourceDescriptions`` list (from the artifact root
            ``extras``); entries without a ``name`` are skipped.
        report: The revision's ``format_metadata.arazzoSources`` block (the COA-1.2 job-summary
            shape: ``sources[]`` and ``unresolved_sources[]``), or ``None`` when absent.

    Returns:
        One ``{name, url, type, status, tier, reason, detail}`` dict per declared source, in
        declaration order. ``status`` is :data:`SOURCE_RESOLVED`, :data:`SOURCE_MISSING` or
        :data:`SOURCE_UNKNOWN`; ``tier`` is set for a resolved source, ``reason`` / ``detail``
        for a missing one.
    """
    report_map = _mapping(report)
    resolved_by_name = {
        str(entry.get("name")): entry
        for entry in _list(report_map.get("sources"))
        if isinstance(entry, Mapping) and entry.get("name")
    }
    missing_by_name = {
        str(entry.get("name")): entry
        for entry in _list(report_map.get("unresolved_sources"))
        if isinstance(entry, Mapping) and entry.get("name")
    }

    views: List[Dict[str, Any]] = []
    for raw in _list(source_descriptions):
        if not isinstance(raw, Mapping) or not raw.get("name"):
            continue
        name = str(raw["name"])
        view: Dict[str, Any] = {
            "name": name,
            "url": raw.get("url") if isinstance(raw.get("url"), str) else None,
            "type": raw.get("type") if isinstance(raw.get("type"), str) else None,
            "status": SOURCE_UNKNOWN,
            "tier": None,
            "reason": None,
            "detail": None,
        }
        if name in resolved_by_name:
            view["status"] = SOURCE_RESOLVED
            view["tier"] = resolved_by_name[name].get("tier")
        elif name in missing_by_name:
            view["status"] = SOURCE_MISSING
            view["reason"] = missing_by_name[name].get("reason")
            view["detail"] = missing_by_name[name].get("detail") or None
        elif report_map:
            # The report itemizes at most a capped number of sources; a declared source the
            # report counted but did not list is resolved when nothing went unresolved.
            if not report_map.get("unresolved"):
                view["status"] = SOURCE_RESOLVED
        views.append(view)
    return views


def step_source_names(step: WorkflowStepRow, declared: Set[str]) -> List[str]:
    """Return the declared source names a step's target points into.

    Reads the ``$sourceDescriptions.<name>`` prefix of ``operationRef`` / ``operationId``, the
    ``sourceDescription`` the normalizer records for an ``operationPath`` target, and — for a
    single-source document — falls back to that one source.

    Args:
        step: The persisted step.
        declared: Names the document's ``sourceDescriptions`` declares.

    Returns:
        Matching declared names (zero or one in practice), in a stable order.
    """
    names: List[str] = []
    explicit = _mapping(step.extras).get("sourceDescription")
    if isinstance(explicit, str) and explicit in declared:
        names.append(explicit)
    hint = parse_operation_ref(
        operation_ref=step.operation_ref, operation_id=step.operation_id
    ).document_hint
    if hint and hint in declared and hint not in names:
        names.append(hint)
    if not names and len(declared) == 1 and (step.operation_ref or step.operation_id):
        names.append(next(iter(declared)))
    return names


def _step_target(step: WorkflowStepRow) -> Dict[str, Optional[str]]:
    """Describe what a step calls: an operation (``operationRef`` / ``operationId``) or a workflow."""
    workflow_target = _mapping(step.extras).get("workflowId")
    if isinstance(workflow_target, str) and workflow_target:
        return {"kind": "workflow", "workflow_id": workflow_target}
    if step.operation_ref or step.operation_id:
        return {"kind": "operation", "workflow_id": None}
    return {"kind": "none", "workflow_id": None}


def _step_view(
    step: WorkflowStepRow,
    operations: Mapping[str, Mapping[str, Any]],
    declared: Set[str],
) -> Dict[str, Any]:
    """Build one step's payload.

    Args:
        step: The persisted step.
        operations: Resolved operation summaries keyed by ``path_operation.id``.
        declared: The document's declared source names.

    Returns:
        The step dict the ``ArazzoWorkflowStepView`` model validates.
    """
    extras = _mapping(step.extras)
    target = _step_target(step)
    operation = (
        dict(operations[step.resolved_path_operation_id])
        if step.resolved_path_operation_id and step.resolved_path_operation_id in operations
        else None
    )
    return {
        "step_id": step.step_id,
        "order_index": step.order_index,
        "description": step.description,
        "target_kind": target["kind"],
        "target_workflow_id": target["workflow_id"],
        "operation_ref": step.operation_ref,
        "operation_id": step.operation_id,
        "resolution_status": step.resolution_status,
        "resolution_reason": step.resolution_reason,
        "operation": operation,
        "source_names": step_source_names(step, declared),
        "parameters": _list(step.parameters),
        "request_body": extras.get("requestBody"),
        "success_criteria": _list(step.success_criteria),
        "on_success": _list(extras.get("onSuccess")),
        "on_failure": _list(step.on_failure),
        "outputs": _mapping(step.outputs),
        "depends_on": _list(step.depends_on),
    }


def step_resolution_counts(steps: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Count a workflow's steps by ``operationRef`` / ``operationId`` resolution state.

    Args:
        steps: Step payloads from :func:`_step_view` (each carries ``resolution_status``).

    Returns:
        ``{status: count}`` for every status that occurs (``resolved``, ``unresolved``,
        ``not_applicable``, ``parse_error``), keys sorted so the payload is stable. Empty for a
        workflow with no steps.
    """
    counts: Dict[str, int] = {}
    for step in steps:
        status = str(step.get("resolution_status") or "")
        if status:
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def build_workflow_views(
    workflows: Sequence[WorkflowRow],
    *,
    operations: Optional[Mapping[str, Mapping[str, Any]]] = None,
    sources: Iterable[Mapping[str, Any]] = (),
) -> List[Dict[str, Any]]:
    """Build the viewer payload for a revision's persisted workflows.

    Args:
        workflows: Rows from :func:`app.arazzo_workflow_persistence.load_arazzo_workflows`.
        operations: Summaries of the operations steps resolved to, keyed by ``path_operation.id``
            (``method``, ``path``, ``path_id``, ``summary``, ``operation_id``, ``project_id``,
            ``project_name``, ``version_id``). A missing entry leaves the step's ``operation``
            ``None`` even when it is ``resolved`` (the target was deleted since import).
        sources: The document's source views from :func:`build_source_views`.

    Returns:
        One dict per workflow, in declaration order, with ``steps`` (ordered), ``sources``
        (the declared sources its steps point into; every declared source when none can be
        attributed, so a workflow never shows an empty status column by accident) and
        ``step_resolution`` (its steps counted by resolution state).
    """
    operation_map = operations or {}
    source_list = [dict(source) for source in sources]
    declared = {str(source["name"]) for source in source_list}

    views: List[Dict[str, Any]] = []
    for workflow in workflows:
        steps = [_step_view(step, operation_map, declared) for step in workflow.steps]
        used = {name for step in steps for name in step["source_names"]}
        workflow_sources = (
            [source for source in source_list if source["name"] in used]
            if used
            else source_list
        )
        extras = _mapping(workflow.extras)
        views.append(
            {
                "workflow_id": workflow.workflow_id,
                "summary": workflow.summary,
                "description": workflow.description,
                "ordinal": workflow.ordinal,
                "inputs": _mapping(workflow.inputs),
                "outputs": _mapping(workflow.outputs),
                "depends_on": _list(extras.get("dependsOn")),
                "success_actions": _list(extras.get("successActions")),
                "failure_actions": _list(extras.get("failureActions")),
                "sources": workflow_sources,
                "step_resolution": step_resolution_counts(steps),
                "steps": steps,
            }
        )
    return views
