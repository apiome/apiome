"""kubeconform check of an emitted CustomResourceDefinition — MFX-21.6 (#4345).

The Kubernetes CRD export (:mod:`app.k8s_crd_emitter`, FMT-2.1) is gated by Apiome's own structural-schema
rules (:func:`app.k8s_structural_schema.validate_k8s_crd_document`). Those rules check the *schema inside*
the CRD the way the API server does; ``kubeconform`` (yannh/kubeconform) checks the *manifest itself*
against the published ``apiextensions.k8s.io/v1`` CustomResourceDefinition schema, the check platform
teams run in CI before ``kubectl apply``. The export gate runs both when the toolchain has kubeconform.

The image installs kubeconform behind a wrapper that points ``-schema-location`` at the CRD schema
cached at build time, so the check needs no network. Run without the wrapper (a developer machine),
kubeconform reads its default online schema location.

The check is strict: kubeconform installed but giving no answer (no JSON on stdout, a resource it could
not validate because the schema could not be found) is a problem, not a pass — the gate must not mistake
"kubeconform did not check" for "kubeconform found nothing" (the rule :func:`app.apiblueprint_drafter.run_drafter`
follows with ``strict=True``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Mapping, Optional

from .toolchain_runner import ToolExecutionError, run_tool_blocking

logger = logging.getLogger(__name__)

__all__ = [
    "KUBECONFORM_ARGS",
    "KUBECONFORM_TIMEOUT_SECONDS",
    "KUBECONFORM_TOOL_KEY",
    "kubeconform_available",
    "read_kubeconform_report",
    "run_kubeconform",
]

#: The bundled-tool registry key (:data:`app.toolchain_packaging.BUNDLED_TOOLS`).
KUBECONFORM_TOOL_KEY = "kubeconform"

#: Wall-clock limit for one run; a CRD is small, so a run that takes longer is stuck.
KUBECONFORM_TIMEOUT_SECONDS = 30.0

#: The arguments of every run: reject unknown fields (``-strict``), print one JSON report with its
#: summary, and read the manifest from stdin (``-``).
KUBECONFORM_ARGS = ("-strict", "-summary", "-output", "json", "-")

#: The resource statuses kubeconform reports; only ``statusValid``, ``statusSkipped`` and ``statusEmpty``
#: are not problems.
_PROBLEM_STATUSES = frozenset({"statusInvalid", "statusError"})


def kubeconform_available() -> bool:
    """Whether the kubeconform binary is installed (a ``PATH`` / override lookup, no subprocess).

    Returns:
        ``True`` when :func:`app.toolchain_packaging.probe_tool` finds the tool.
    """
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    probe = probe_tool(KUBECONFORM_TOOL_KEY)
    return bool(probe and probe.available)


def read_kubeconform_report(stdout: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Read the problems out of kubeconform's ``-output json`` report.

    Args:
        stdout: What kubeconform printed: ``{"resources": [...], "summary": {...}}``. With ``-output json``
            and no ``-verbose``, ``resources`` lists only the resources that are not valid.

    Returns:
        One problem per ``validationErrors`` entry of an invalid resource (``message`` prefixed with its
        JSON ``path``), or one per invalid / unvalidated resource without them — each a dict with
        ``message``, ``path`` (or ``None``), ``status`` and the resource ``kind`` / ``name``. ``[]`` when
        every resource is valid; ``None`` when ``stdout`` holds no report.
    """
    if not stdout or not stdout.strip():
        return None
    try:
        report = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(report, Mapping):
        return None
    resources = report.get("resources")
    if resources is None and isinstance(report.get("summary"), Mapping):
        return []
    if not isinstance(resources, list):
        return None
    problems: List[Dict[str, Any]] = []
    for resource in resources:
        if not isinstance(resource, Mapping) or resource.get("status") not in _PROBLEM_STATUSES:
            continue
        base = {"status": resource.get("status"), "kind": resource.get("kind"), "name": resource.get("name")}
        errors = [error for error in resource.get("validationErrors") or [] if isinstance(error, Mapping)]
        if errors:
            problems.extend(
                {**base, "path": error.get("path") or None,
                 "message": f"{error.get('path') or '/'}: {error.get('msg') or 'is not valid'}"}
                for error in errors
            )
        else:
            problems.append({**base, "path": None, "message": str(resource.get("msg") or "kubeconform could not "
                                                                   "validate the resource")})
    return problems


def run_kubeconform(text: str) -> List[Dict[str, Any]]:
    """Run kubeconform on one CustomResourceDefinition manifest.

    Args:
        text: The emitted CRD (YAML or JSON).

    Returns:
        The problems (:func:`read_kubeconform_report`); empty when kubeconform accepts the manifest.

    Raises:
        ToolNotAvailableError: When kubeconform is not installed (callers check
            :func:`kubeconform_available` first).
        ToolchainError: When kubeconform failed to run (a timeout, a resource limit…).
        ValueError: When kubeconform printed no report.
    """
    try:
        result = run_tool_blocking(
            KUBECONFORM_TOOL_KEY, list(KUBECONFORM_ARGS), stdin=text, timeout=KUBECONFORM_TIMEOUT_SECONDS,
            thread_name="kubeconform",
        )
        stdout = result.stdout
    except ToolExecutionError as exc:
        # kubeconform exits 1 when a resource is invalid; its report is still on stdout.
        stdout = exc.stdout
    problems = read_kubeconform_report(stdout)
    if problems is None:
        raise ValueError("kubeconform printed no report")
    return problems
