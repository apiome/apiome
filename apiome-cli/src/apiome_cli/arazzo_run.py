"""Build and report an Arazzo workflow run — ``apiome arazzo run`` (COA-1.7, #7043).

``apiome arazzo run WORKFLOW_ID --target …`` posts to
``POST /v1/workflows/{tenant}/versions/{version_id}/workflows/{workflow_id}/run``, which executes
the stored workflow step by step against an ECA-1.2 verification target (a deployment or a
``mock`` target) and answers with a per-step report. This module is the pure half of the command:
it turns ``--input`` / ``--inputs`` / ``--fixtures`` into the request body, renders the report
(each criterion with its expected and actual value) and maps the response to an exit code. The
flags and HTTP calls live in :mod:`apiome_cli.commands.arazzo`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from apiome_cli.exit_codes import (
    EXIT_ARAZZO_RUN_FAILED,
    EXIT_POLICY_BLOCKED,
    EXIT_SUCCESS,
)
from apiome_cli.import_.yaml_load import safe_load

#: Refusal codes that mean "the CTG-4.3 safety model held a mutating step back".
MUTATION_REFUSAL_CODES = frozenset({"mutating-method-blocked", "mutating-fixture-missing"})

#: Run outcome that exits 0.
PASSED_OUTCOME = "passed"


def _read_structured(path: Path, what: str) -> Any:
    """Read a JSON or YAML file.

    Args:
        path: The file to read.
        what: The flag the file came from, for error messages.

    Returns:
        The parsed document.

    Raises:
        ValueError: When the file cannot be read or parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{what}: cannot read {path}: {exc.strerror or exc}") from exc
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return safe_load(text)
    except Exception as exc:
        raise ValueError(f"{what}: {path} is neither JSON nor YAML: {exc}") from exc


def parse_input_pairs(pairs: Sequence[str] | None) -> dict[str, Any]:
    """Parse repeatable ``--input NAME=VALUE`` flags.

    A value that parses as JSON keeps its type (``count=3`` is a number, ``tags=["a"]`` a list,
    ``ok=true`` a boolean); anything else is a string, so ``status=available`` needs no quotes.

    Args:
        pairs: Raw ``NAME=VALUE`` strings, or ``None``.

    Returns:
        ``{name: value}``.

    Raises:
        ValueError: When an entry has no ``=`` or an empty name.
    """
    values: dict[str, Any] = {}
    for raw in pairs or ():
        name, sep, value = (raw or "").partition("=")
        name = name.strip()
        if not sep or not name:
            raise ValueError(f"input must be NAME=VALUE, got {raw!r}")
        try:
            values[name] = json.loads(value)
        except ValueError:
            values[name] = value
    return values


def load_inputs(path: Path | None, pairs: Sequence[str] | None) -> dict[str, Any]:
    """Combine an ``--inputs`` file with ``--input`` flags (flags win).

    Args:
        path: A JSON or YAML file holding an object of inputs, or ``None``.
        pairs: ``--input NAME=VALUE`` flags.

    Returns:
        The workflow inputs.

    Raises:
        ValueError: When the file is unreadable, not an object, or a flag is malformed.
    """
    inputs: dict[str, Any] = {}
    if path is not None:
        document = _read_structured(path, "--inputs")
        if not isinstance(document, Mapping):
            raise ValueError(f"--inputs: {path} must hold an object of input values")
        inputs.update(document)
    inputs.update(parse_input_pairs(pairs))
    return inputs


def load_fixtures(path: Path | None) -> list[dict[str, Any]]:
    """Read ``--fixtures``: a list of mutating fixtures, or ``{"fixtures": [...]}``.

    Each fixture names the operation it unlocks (``operation_key``, e.g. ``POST /pets``) and may
    narrow it to one step (``case_id``: the ``stepId``) or override parameters and the body.

    Args:
        path: The JSON or YAML file, or ``None``.

    Returns:
        The fixtures (empty without a file).

    Raises:
        ValueError: When the file is unreadable or not a list of objects.
    """
    if path is None:
        return []
    document = _read_structured(path, "--fixtures")
    if isinstance(document, Mapping):
        document = document.get("fixtures")
    if not isinstance(document, list) or not all(isinstance(item, Mapping) for item in document):
        raise ValueError(f"--fixtures: {path} must hold a list of fixture objects")
    return [dict(item) for item in document]


def build_run_body(
    *,
    target: str,
    inputs: Mapping[str, Any],
    allow_mutating: bool,
    fixtures: Sequence[Mapping[str, Any]],
    idempotency_key: str | None = None,
    context: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the ``ArazzoWorkflowRunRequest`` body.

    Args:
        target: Verification target slug or id.
        inputs: Workflow inputs.
        allow_mutating: ``--allow-mutating``.
        fixtures: Mutating fixtures from ``--fixtures``.
        idempotency_key: Evidence retry key.
        context: Non-secret CI context.

    Returns:
        The JSON body.
    """
    body: dict[str, Any] = {
        "target_ref": target,
        "inputs": dict(inputs),
        "verification": {"allow_mutating": allow_mutating, "fixtures": [dict(f) for f in fixtures]},
    }
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    if context:
        body["context"] = dict(context)
    return body


def exit_code_for_run(payload: Mapping[str, Any]) -> int:
    """Map a run response to the process exit code.

    Args:
        payload: The ``ArazzoWorkflowRunResponse`` body.

    Returns:
        ``0`` when the run executed and passed; :data:`EXIT_POLICY_BLOCKED` (3) when it was refused
        because a mutating step lacked policy, opt-in or fixture; :data:`EXIT_ARAZZO_RUN_FAILED`
        (7) when another refusal stopped it, or when it executed and a step failed or errored.
    """
    if not payload.get("ok"):
        codes = {str(r.get("code")) for r in payload.get("refusals") or [] if isinstance(r, Mapping)}
        if codes and codes <= MUTATION_REFUSAL_CODES:
            return EXIT_POLICY_BLOCKED
        return EXIT_ARAZZO_RUN_FAILED
    report = payload.get("report") or {}
    if str(report.get("outcome") or "").lower() == PASSED_OUTCOME:
        return EXIT_SUCCESS
    return EXIT_ARAZZO_RUN_FAILED


def refusal_lines(payload: Mapping[str, Any]) -> list[str]:
    """Describe why a run was refused, one line per refusal and fixture finding."""
    lines = []
    for refusal in payload.get("refusals") or []:
        if not isinstance(refusal, Mapping):
            continue
        where = f"{refusal.get('step_id')}: " if refusal.get("step_id") else ""
        lines.append(f"  {where}[{refusal.get('code')}] {refusal.get('message')}")
    lines.extend(fixture_lines(payload))
    return lines


def fixture_lines(payload: Mapping[str, Any]) -> list[str]:
    """Describe fixtures that matched no mutating step."""
    return [
        f"  fixture {finding.get('operation_key')}: [{finding.get('code')}] {finding.get('message')}"
        for finding in payload.get("fixture_findings") or []
        if isinstance(finding, Mapping)
    ]


def _criterion_line(criterion: Mapping[str, Any]) -> str:
    """One criterion as ``✓/✗ expected — actual``."""
    mark = {"passed": "ok  ", "failed": "FAIL", "error": "ERR "}.get(str(criterion.get("outcome")), "?   ")
    implicit = " (implicit)" if criterion.get("implicit") else ""
    line = f"      {mark} {criterion.get('expected')}{implicit}"
    if criterion.get("outcome") != "passed":
        line += f"  — actual: {criterion.get('actual')}"
        if criterion.get("outcome") == "error" and criterion.get("message"):
            line += f" ({criterion.get('message')})"
    return line


def report_lines(payload: Mapping[str, Any], *, workflow_id: str, target: str) -> list[str]:
    """Render an executed run: header, one block per step with its criteria, then outputs.

    Args:
        payload: The ``ArazzoWorkflowRunResponse`` body (``ok`` true).
        workflow_id: The workflow that ran.
        target: The ``--target`` value.

    Returns:
        Lines for stdout.
    """
    report = payload.get("report") or {}
    run = payload.get("run") or {}
    counts = report.get("counts") or {}
    target_info = report.get("target") or {}
    lines = [
        f"Arazzo workflow {workflow_id} → target {target} — {report.get('outcome')}",
        f"  evidence: {run.get('id') or '(not recorded)'}",
        f"  digest: {payload.get('digest')}",
        (
            f"  target: {target_info.get('slug')} ({target_info.get('environment')}) "
            f"{target_info.get('base_url')}"
        ),
        (
            "  steps: {executed} executed of {steps}, {passed} passed, {failed} failed, "
            "{errored} errored"
        ).format(
            executed=counts.get("executed", 0),
            steps=counts.get("steps", 0),
            passed=counts.get("passed", 0),
            failed=counts.get("failed", 0),
            errored=counts.get("errored", 0),
        ),
    ]
    for step in report.get("steps") or []:
        if not isinstance(step, Mapping):
            continue
        execution = f" (#{step.get('execution')})" if (step.get("execution") or 1) > 1 else ""
        status = step.get("status_code")
        attempts = f", {step.get('attempts')} attempts" if (step.get("attempts") or 1) > 1 else ""
        lines.append(
            f"  {step.get('outcome', '?'):<7} {step.get('step_id')}{execution}  "
            f"{step.get('method')} {step.get('path')}  → {status if status is not None else '—'}"
            f"{attempts}"
        )
        if step.get("failure_code"):
            lines.append(f"      [{step.get('failure_code')}] {step.get('failure_message')}")
        for criterion in step.get("criteria") or []:
            if isinstance(criterion, Mapping):
                lines.append(_criterion_line(criterion))
        action = step.get("action") or {}
        if action.get("type") == "goto":
            lines.append(f"      then goto {action.get('step_id')}")
        elif action.get("type") == "retry":
            lines.append("      then retry")
    if report.get("not_reached"):
        lines.append(f"  not reached: {', '.join(str(s) for s in report['not_reached'])}")
    outputs = report.get("outputs") or {}
    if outputs:
        lines.append("  outputs:")
        lines.extend(f"    {name}: {json.dumps(value)}" for name, value in outputs.items())
    for error in report.get("output_errors") or []:
        lines.append(f"  output error: {error}")
    lines.extend(fixture_lines(payload))
    return lines
