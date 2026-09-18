"""Pure helpers for ``apiome checks`` — the API change check suite (GNC-3.1 / #4740).

The server decides everything: which components apply, what each one says, and the verdict. This
module only shapes the request, maps the verdict onto a process exit code, and renders the
evaluation for a terminal. No HTTP and no typer here, so every rule is testable on its own.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from apiome_cli.exit_codes import EXIT_CHECK_FAILED, EXIT_CHECK_PENDING, EXIT_SUCCESS

#: Output formats: a human summary, the raw API JSON, or the markdown the pull request shows.
FORMATS = ("text", "json", "md")

#: Verdict → exit code. ``skipped`` is a success: none of the required checks applied, which is not
#: a failure of the change (and the publish gate treats it the same way).
_EXIT_BY_STATE = {
    "pass": EXIT_SUCCESS,
    "skipped": EXIT_SUCCESS,
    "fail": EXIT_CHECK_FAILED,
    "pending": EXIT_CHECK_PENDING,
}


def build_run_request(
    *,
    commit_sha: Optional[str] = None,
    pr_number: Optional[int] = None,
    publish: bool = True,
) -> dict[str, Any]:
    """Build the ``POST …/check-suite`` body.

    :param commit_sha: The commit to report against; omitted to use the commit the draft is
        synchronized with.
    :param pr_number: The pull request the commit belongs to, when known.
    :param publish: Whether to put the verdict on the provider as well as recording it.
    :returns: The JSON body; absent fields take the server's defaults.
    """
    body: dict[str, Any] = {"publish": bool(publish)}
    commit = (commit_sha or "").strip()
    if commit:
        body["commit_sha"] = commit
    if pr_number is not None:
        body["pr_number"] = int(pr_number)
    return body


def exit_code_for_state(state: object) -> int:
    """Map an evaluation's state onto a process exit code.

    :param state: ``pending`` / ``pass`` / ``fail`` / ``skipped`` as the server reported it.
    :returns: ``0`` for pass or skipped, :data:`EXIT_CHECK_FAILED` for fail,
        :data:`EXIT_CHECK_PENDING` for pending. Anything else is a failed check: an answer the
        CLI does not understand must never read as a green light.
    """
    return _EXIT_BY_STATE.get(str(state or "").strip().lower(), EXIT_CHECK_FAILED)


def _state_label(component: Mapping[str, Any]) -> str:
    """One component's result as the table shows it."""
    state = str(component.get("state") or "?")
    return f"{state} (warning)" if component.get("warned") else state


def format_text(payload: Mapping[str, Any], *, subject: str) -> list[str]:
    """Render an evaluation for a terminal.

    :param payload: The ``CheckSuiteRunDetail`` JSON.
    :param subject: How to name the version (``project@version``).
    :returns: Lines to print on stdout.
    """
    run = payload.get("run") or {}
    components = [c for c in (run.get("components") or []) if isinstance(c, Mapping)]
    lines = [
        f"API change check — {subject}: {run.get('state', '?')} ({run.get('reason', '?')})",
    ]
    deciding = [
        c for c in components if c.get("counted") and c.get("state") in ("fail", "pending")
    ]
    for component in deciding:
        lines.append(f"  {component.get('label') or component.get('component')}: {component.get('detail')}")
    if not components:
        lines.append(f"  {run.get('title') or 'No component was judged at this commit.'}")
    else:
        lines.append("")
        width = max(len(str(c.get("component") or "")) for c in components)
        lines.append(f"  {'CHECK'.ljust(width)}  {'POLICY':<9} {'RESULT':<18} REASON")
        for component in components:
            lines.append(
                f"  {str(component.get('component') or '').ljust(width)}  "
                f"{str(component.get('requirement') or ''):<9} {_state_label(component):<18} "
                f"{component.get('reason') or ''}"
            )
    lines.append("")
    replay = " (replayed — same inputs, same evidence)" if payload.get("replayed") else ""
    lines.append(f"  evaluation: {run.get('id')}{replay}")
    if run.get("commit_sha"):
        lines.append(f"  commit: {run.get('commit_sha')}")
    provider = payload.get("provider")
    check = (payload.get("check") or {}).get("check") or {}
    if isinstance(provider, Mapping):
        if provider.get("recorded"):
            outcome = check.get("last_publish_outcome") or "recorded, not published"
            lines.append(f"  pull request: {check.get('name')} — {outcome}")
        else:
            lines.append(
                f"  pull request: not reported ({provider.get('reason')}): {provider.get('message')}"
            )
    if payload.get("stale"):
        lines.append(
            "  stale: the draft or the policy has changed since this evaluation — run it again."
        )
    return lines
