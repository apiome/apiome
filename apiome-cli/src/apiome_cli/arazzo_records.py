"""Read and check the Arazzo workflow records a revision stores — ``apiome arazzo`` (COA-1.5, #7041).

An Arazzo import persists each workflow and its ordered steps; the REST reads under
``/v1/workflows/{tenant}/…`` return them with every step's ``operationRef`` / ``operationId``
resolution state and every source description's status. This module is the pure half of
``apiome arazzo``: it turns those payloads into tables and into the problems ``validate``
reports. The HTTP calls and flags live in :mod:`apiome_cli.commands.arazzo`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import typer
from rich.table import Table

from apiome_cli.output import ListColumn, emit_list_table, emit_record_table
from apiome_cli.terminal import make_console

#: Step resolution states that mean the step's target could not be matched to an operation.
UNRESOLVED_STEP_STATES = frozenset({"unresolved", "parse_error"})

#: The source-description status that means no resolution tier found the document.
MISSING_SOURCE_STATUS = "missing"


def _text(value: Any) -> str:
    """Render ``None`` as an empty cell and anything else as ``str``."""
    return "" if value is None else str(value)


def _list(value: Any) -> list[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return list(value) if isinstance(value, list) else []


def step_counts(workflow: Mapping[str, Any]) -> dict[str, int]:
    """Count a workflow's steps by resolution state.

    Prefers the server's ``step_resolution`` block; counts the steps itself when an older server
    did not send one.

    Args:
        workflow: One workflow from a REST workflows payload.

    Returns:
        ``{status: count}`` for every state that occurs.
    """
    counts = workflow.get("step_resolution")
    if isinstance(counts, Mapping) and counts:
        return {str(key): int(value) for key, value in counts.items()}
    tally: dict[str, int] = {}
    for step in _list(workflow.get("steps")):
        status = str(step.get("resolution_status") or "") if isinstance(step, Mapping) else ""
        if status:
            tally[status] = tally.get(status, 0) + 1
    return tally


def workflow_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a workflows payload into one table row per workflow.

    Args:
        payload: The REST ``ArazzoWorkflowsResponse`` body.

    Returns:
        Rows with ``workflow_id``, ``summary``, ``steps`` (count), ``resolved`` and ``unresolved``
        (steps whose target did not resolve, including parse errors).
    """
    rows: list[dict[str, Any]] = []
    for workflow in _list(payload.get("workflows")):
        if not isinstance(workflow, Mapping):
            continue
        counts = step_counts(workflow)
        rows.append(
            {
                "workflow_id": workflow.get("workflow_id"),
                "summary": workflow.get("summary"),
                "steps": len(_list(workflow.get("steps"))),
                "resolved": counts.get("resolved", 0),
                "unresolved": sum(counts.get(state, 0) for state in UNRESOLVED_STEP_STATES),
            }
        )
    return rows


_WORKFLOW_COLUMNS: tuple[ListColumn, ...] = (
    ("Workflow ID", "workflow_id", None),
    ("Steps", "steps", None),
    ("Resolved", "resolved", None),
    ("Unresolved", "unresolved", None),
    ("Summary", "summary", _text),
)


def emit_workflows_table(payload: Mapping[str, Any]) -> None:
    """Print a revision's workflows as a table (``apiome arazzo list``).

    Args:
        payload: The REST ``ArazzoWorkflowsResponse`` body.
    """
    rows = workflow_rows(payload)
    emit_list_table(rows, _WORKFLOW_COLUMNS, total=len(rows), empty_message="No Arazzo workflows.")


def find_workflow(payload: Mapping[str, Any], workflow_id: str) -> dict[str, Any] | None:
    """Return the workflow whose ``workflow_id`` equals ``workflow_id`` (exact match), or ``None``."""
    for workflow in _list(payload.get("workflows")):
        if isinstance(workflow, Mapping) and workflow.get("workflow_id") == workflow_id:
            return dict(workflow)
    return None


def step_target(step: Mapping[str, Any]) -> str:
    """Describe what a step calls: the ``workflowId``, ``operationRef`` or ``operationId``."""
    if step.get("target_kind") == "workflow":
        return f"workflow {_text(step.get('target_workflow_id'))}"
    return _text(step.get("operation_ref") or step.get("operation_id"))


def step_operation(step: Mapping[str, Any]) -> str:
    """Describe the operation a step resolved to as ``METHOD /path``, or an empty string."""
    operation = step.get("operation")
    if not isinstance(operation, Mapping):
        return ""
    return f"{_text(operation.get('method'))} {_text(operation.get('path'))}".strip()


def emit_workflow_detail(workflow: Mapping[str, Any]) -> None:
    """Print one workflow, its sources and its ordered steps (``apiome arazzo show``).

    Args:
        workflow: One workflow from a REST workflows payload.
    """
    counts = step_counts(workflow)
    emit_record_table(
        dict(workflow),
        (
            ("Workflow ID", "workflow_id", None),
            ("Summary", "summary", _text),
            ("Description", "description", _text),
            (
                "Sources",
                "sources",
                lambda sources: ", ".join(
                    f"{source.get('name')} ({source.get('status')})"
                    for source in _list(sources)
                    if isinstance(source, Mapping)
                ),
            ),
            (
                "Step resolution",
                "step_resolution",
                lambda _value: ", ".join(f"{key} {value}" for key, value in counts.items()),
            ),
        ),
    )
    steps = [step for step in _list(workflow.get("steps")) if isinstance(step, Mapping)]
    typer.echo("")
    if not steps:
        typer.echo("Steps: (none)")
        return
    table = Table(show_header=True, header_style="bold")
    for column in ("#", "Step ID", "Target", "Resolution", "Operation"):
        table.add_column(column)
    for step in steps:
        table.add_row(
            _text(step.get("order_index")),
            _text(step.get("step_id")),
            step_target(step),
            _text(step.get("resolution_status")),
            step_operation(step),
        )
    make_console().print(table)


def record_problems(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """List what makes a revision's stored workflows fail ``apiome arazzo validate``.

    A step fails when its target is ``unresolved`` or could not be parsed (``parse_error``); a
    source fails when it is ``missing``. Sources whose status is ``unknown`` (imported before the
    resolution report was recorded) and steps that call a workflow (``not_applicable``) pass.

    Args:
        payload: The REST ``ArazzoWorkflowsResponse`` body.

    Returns:
        One problem dict per failure, sources first: ``{kind: "source", name, reason, detail}`` or
        ``{kind: "step", workflow_id, step_id, status, reason, target}``.
    """
    problems: list[dict[str, Any]] = []
    for source in _list(payload.get("sources")):
        if isinstance(source, Mapping) and source.get("status") == MISSING_SOURCE_STATUS:
            problems.append(
                {
                    "kind": "source",
                    "name": source.get("name"),
                    "reason": source.get("reason"),
                    "detail": source.get("detail"),
                }
            )
    for workflow in _list(payload.get("workflows")):
        if not isinstance(workflow, Mapping):
            continue
        for step in _list(workflow.get("steps")):
            if isinstance(step, Mapping) and step.get("resolution_status") in UNRESOLVED_STEP_STATES:
                problems.append(
                    {
                        "kind": "step",
                        "workflow_id": workflow.get("workflow_id"),
                        "step_id": step.get("step_id"),
                        "status": step.get("resolution_status"),
                        "reason": step.get("resolution_reason"),
                        "target": step_target(step),
                    }
                )
    return problems


def describe_problem(problem: Mapping[str, Any]) -> str:
    """Render one :func:`record_problems` entry as a single stderr line."""
    reason = problem.get("reason")
    suffix = f" ({reason})" if reason else ""
    if problem.get("kind") == "source":
        return f"source {problem.get('name')}: missing{suffix}"
    return (
        f"{problem.get('workflow_id')}/{problem.get('step_id')}: {problem.get('status')} "
        f"target {problem.get('target')}{suffix}"
    )


def document_summary(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize a structurally valid Arazzo document for ``apiome arazzo validate FILE``.

    Args:
        doc: The parsed, validated document.

    Returns:
        ``{arazzo, workflows, steps, sources}``: the declared version and the counts.
    """
    workflows: Sequence[Any] = _list(doc.get("workflows"))
    return {
        "arazzo": doc.get("arazzo"),
        "workflows": len(workflows),
        "steps": sum(
            len(_list(workflow.get("steps"))) for workflow in workflows if isinstance(workflow, Mapping)
        ),
        "sources": len(_list(doc.get("sourceDescriptions"))),
    }
