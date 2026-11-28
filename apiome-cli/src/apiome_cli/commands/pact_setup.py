"""``apiome pact setup`` — the Contracts guided set-up for scripted workspaces, PFX-8.20 (#7317).

The same six sections the **Set up contracts** page walks through
(``/v1/tenants/{t}/pact-setup``), as one command that can be run again and again:

* with no flag it shows the sections — Done, Next, To do (``pacts:view``);
* ``--from-projects`` creates a pacticipant for every project and registered repository the
  workspace proposes that has none yet (``POST …/pacticipants``);
* ``--environments production,staging`` creates the environments that do not exist
  (``POST …/pact-broker/environments``); ``production`` is marked production, and
  ``--require-contract`` makes can-i-deploy there require a contract;
* ``--ci github`` opens a pull request adding can-i-deploy and record-deployment in every registered
  GitHub repository that belongs to a pacticipant, and prints the workflow for the ones it could not
  open one in (``POST …/pact-setup/github/pull-requests``);
* ``--write-secrets`` stores this command's own broker address and key as the two Actions secrets
  in those repositories (``POST …/pact-setup/github/secrets``).

Everything that already exists is reported as already there and left alone, so a second run sets
nothing up twice. Nothing is dropped silently: every pacticipant, environment and repository ends as
one line. ``--dry-run`` prints what a run would do and changes nothing. The exit code is 1 when
anything failed, 0 otherwise — a repository skipped with a reason is not a failure.

Like the rest of ``apiome pact`` the address and key come from ``PACT_BROKER_BASE_URL`` /
``PACT_BROKER_TOKEN`` (or ``-b`` / ``-k``).
"""

from __future__ import annotations

from typing import Any, Optional

import click
import typer

from apiome_cli.client.pact_broker_connection import (
    BrokerConnection,
    connect,
    resolve_broker_settings,
)
from apiome_cli.client.pact_broker_requests import build_environment_body
from apiome_cli.commands.pact_broker import (
    BROKER_BASE_URL,
    BROKER_TOKEN,
    OUTPUT,
    _emit,
    _format,
)
from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.pact_setup_output import setup_lines

__all__ = [
    "CI_SYSTEMS",
    "parse_environments",
    "pull_request_repositories",
    "setup",
    "wanted_pacticipants",
]

#: The CI systems ``--ci`` can wire. The others have recipes on Settings → CI and commit statuses.
CI_SYSTEMS = ("github",)

_SETUP = "/pact-setup"
_COMMAND = "setup"


def parse_environments(value: Optional[str]) -> list[str]:
    """``--environments production,staging`` as names, in order, once each.

    Args:
        value: The flag's value, or ``None``.

    Returns:
        The names.

    Raises:
        ValueError: For an empty name or one with whitespace. Nothing is dropped silently.
    """
    if value is None:
        return []
    names: list[str] = []
    for raw in value.split(","):
        name = raw.strip()
        if not name:
            raise ValueError(
                "--environments has an empty name: give names separated by commas, e.g. production,staging"
            )
        if any(ch.isspace() for ch in name):
            raise ValueError(
                f"environment '{name}' has a space: an environment name is one word"
            )
        if name not in names:
            names.append(name)
    return names


def wanted_pacticipants(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The proposed pacticipants that do not exist yet.

    Args:
        state: The ``GET …/pact-setup`` document.

    Returns:
        The candidates with no ``pacticipant``, in the document's order.
    """
    return [
        item
        for item in state.get("candidates") or []
        if isinstance(item, dict) and not item.get("pacticipant")
    ]


def pull_request_repositories(
    state: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Which GitHub repositories ``--ci github`` asks about, and which it cannot.

    A repository can be asked about when a pacticipant's repository URL names it: the workflow needs
    the pacticipant can-i-deploy asks about.

    Args:
        state: The ``GET …/pact-setup`` document.

    Returns:
        The request rows (``{repository_id, pacticipant}``), and the repositories left out as
        ``skipped`` actions with the reason.
    """
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    for repository in (state.get("github") or {}).get("repositories") or []:
        name = repository.get("pacticipant_name")
        if name:
            rows.append(
                {"repository_id": str(repository["id"]), "pacticipant": str(name)}
            )
        else:
            skipped.append(
                {
                    "kind": "pull request",
                    "name": str(repository.get("full_name")),
                    "outcome": "skipped",
                    "detail": "no pacticipant has this repository as its repository URL; set it "
                    "(apiome pact create-or-update-pacticipant --repository-url) and run again",
                }
            )
    return rows, skipped


def _read(conn: BrokerConnection) -> dict[str, Any]:
    """The set-up."""
    return conn.client.get(conn.api_path(_SETUP, command=_COMMAND)).json()


def _refusal(response: Any) -> str:
    """The server's message from a refused request."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        detail = detail.get("message")
    return str(
        detail
        or (body.get("message") if isinstance(body, dict) else None)
        or f"HTTP {response.status_code}"
    )


def _create_pacticipants(
    conn: BrokerConnection, state: dict[str, Any], *, dry_run: bool
) -> list[dict[str, Any]]:
    """Create each proposed pacticipant that has none; list the ones that exist."""
    actions: list[dict[str, Any]] = []
    for candidate in state.get("candidates") or []:
        name = str(candidate.get("name"))
        if candidate.get("pacticipant"):
            actions.append(
                {
                    "kind": "pacticipant",
                    "name": name,
                    "outcome": "exists",
                    "detail": str(candidate["pacticipant"]),
                }
            )
            continue
        if dry_run:
            actions.append(
                {
                    "kind": "pacticipant",
                    "name": name,
                    "outcome": "would",
                    "detail": str(candidate.get("source_label") or ""),
                }
            )
            continue
        body = {"name": name}
        for field, key in (
            ("main_branch", "main_branch"),
            ("repository_url", "repository_url"),
            ("project", "project"),
        ):
            if candidate.get(key):
                body[field] = str(candidate[key])
        response = conn.client.post_raw(
            conn.api_path("/pacticipants", command=_COMMAND), json=body
        )
        if response.status_code < 300:
            actions.append(
                {
                    "kind": "pacticipant",
                    "name": name,
                    "outcome": "created",
                    "detail": str(candidate.get("source_label") or ""),
                }
            )
        elif response.status_code == 409:
            actions.append(
                {
                    "kind": "pacticipant",
                    "name": name,
                    "outcome": "exists",
                    "detail": _refusal(response),
                }
            )
        else:
            actions.append(
                {
                    "kind": "pacticipant",
                    "name": name,
                    "outcome": "failed",
                    "detail": _refusal(response),
                }
            )
    omitted = int(state.get("candidates_omitted") or 0)
    if omitted:
        actions.append(
            {
                "kind": "pacticipant",
                "name": f"{omitted} more",
                "outcome": "skipped",
                "detail": "the proposal lists the first 200 projects and repositories; create the rest with "
                "apiome pact create-or-update-pacticipant",
            }
        )
    return actions


def _create_environments(
    conn: BrokerConnection,
    state: dict[str, Any],
    names: list[str],
    *,
    require_contract: bool,
    dry_run: bool,
) -> list[dict[str, Any]]:
    """Create each named environment that does not exist."""
    existing = {
        str(name).lower()
        for name in (state.get("facts") or {}).get("environments") or []
    }
    actions: list[dict[str, Any]] = []
    for name in names:
        if name.lower() in existing:
            actions.append({"kind": "environment", "name": name, "outcome": "exists"})
            continue
        production = name.lower() == "production"
        if dry_run:
            actions.append(
                {
                    "kind": "environment",
                    "name": name,
                    "outcome": "would",
                    "detail": "production" if production else "",
                }
            )
            continue
        body = build_environment_body(
            name=name,
            display_name=None,
            production=production,
            contract_required=production and require_contract,
            contact_name=None,
            contact_email_address=None,
        )
        response = conn.client.post_raw(conn.broker_path("/environments"), json=body)
        if response.status_code < 300:
            actions.append(
                {
                    "kind": "environment",
                    "name": name,
                    "outcome": "created",
                    "detail": "production" if production else "",
                }
            )
        elif response.status_code == 409:
            actions.append({"kind": "environment", "name": name, "outcome": "exists"})
        else:
            actions.append(
                {
                    "kind": "environment",
                    "name": name,
                    "outcome": "failed",
                    "detail": _refusal(response),
                }
            )
    return actions


def setup(
    ctx: typer.Context,
    from_projects: bool = typer.Option(
        False,
        "--from-projects",
        help="Create a pacticipant for each proposed project and repository that has none.",
    ),
    environments: Optional[str] = typer.Option(
        None,
        "--environments",
        help="Create these environments if missing, comma-separated: production,staging.",
    ),
    require_contract: bool = typer.Option(
        False,
        "--require-contract",
        help="With --environments: can-i-deploy to production requires a contract.",
    ),
    ci: Optional[str] = typer.Option(
        None,
        "--ci",
        help="Open pull requests adding can-i-deploy and record-deployment. Only: github.",
    ),
    ci_environment: Optional[str] = typer.Option(
        None,
        "--ci-environment",
        help="The environment the pipeline asks about (default: production, else the first).",
    ),
    write_secrets: bool = typer.Option(
        False,
        "--write-secrets",
        help="Store this command's broker address and key as Actions secrets in the workspace's GitHub repositories.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print what a run would do; change nothing."
    ),
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Set up contracts: pacticipants, environments and pipelines, or show how far the set-up is.

    With no flag, shows the six sections of the guided set-up (GET …/pact-setup). Each flag sets one
    part up and leaves what already exists alone, so the command can be run again. Reading needs
    pacts:view, creating pacts:create, --ci and --write-secrets pacts:delete. Exits 1 when anything
    failed; a repository skipped with a reason is not a failure.
    """
    fmt = _format(ctx, output)
    try:
        names = parse_environments(environments)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--environments") from exc
    if ci is not None and ci not in CI_SYSTEMS:
        raise typer.BadParameter(
            f"'{ci}' is not wired by this command (only: {', '.join(CI_SYSTEMS)}). GitLab CI, Jenkins and Azure "
            "Pipelines have recipes on Contracts → Settings → CI and commit statuses.",
            param_hint="--ci",
        )
    if require_contract and "production" not in [name.lower() for name in names]:
        raise typer.BadParameter(
            "--require-contract needs production in --environments",
            param_hint="--require-contract",
        )
    if ci_environment is not None and ci is None:
        raise typer.BadParameter(
            "--ci-environment needs --ci github", param_hint="--ci-environment"
        )

    conn = connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)
    state = _read(conn)
    actions: list[dict[str, Any]] = []
    pull_requests: list[dict[str, Any]] = []

    if from_projects:
        actions += _create_pacticipants(conn, state, dry_run=dry_run)
    if names:
        actions += _create_environments(
            conn, state, names, require_contract=require_contract, dry_run=dry_run
        )
    if (from_projects or names) and not dry_run and (ci or write_secrets):
        # The pull requests need the pacticipants and environments just created.
        state = _read(conn)

    if write_secrets:
        settings, _address = resolve_broker_settings(
            ctx, broker_base_url=broker_base_url, broker_token=broker_token
        )
        key = settings.api_key_value()
        address = f"{str(settings.base_url).rstrip('/')}/v1/tenants/{conn.tenant(command=_COMMAND)}/pact-broker"
        writable = [
            item
            for item in (state.get("github") or {}).get("repositories") or []
            if item.get("linked")
        ]
        left_out = [
            item
            for item in (state.get("github") or {}).get("repositories") or []
            if not item.get("linked")
        ]
        for repository in left_out:
            actions.append(
                {
                    "kind": "secrets",
                    "name": str(repository.get("full_name")),
                    "outcome": "skipped",
                    "detail": "registered without a linked GitHub account; set PACT_BROKER_BASE_URL and "
                    "PACT_BROKER_TOKEN there by hand (gh secret set)",
                }
            )
        if not writable:
            reason = (state.get("github") or {}).get(
                "reason"
            ) or "no GitHub repository can be written to"
            actions.append(
                {
                    "kind": "secrets",
                    "name": "GitHub",
                    "outcome": "skipped",
                    "detail": str(reason),
                }
            )
        elif dry_run:
            actions += [
                {
                    "kind": "secrets",
                    "name": str(item.get("full_name")),
                    "outcome": "would",
                }
                for item in writable
            ]
        else:
            response = conn.client.post_raw(
                conn.api_path(f"{_SETUP}/github/secrets", command=_COMMAND),
                json={
                    "repository_ids": [str(item["id"]) for item in writable],
                    "broker_base_url": address,
                    "token": key,
                },
            )
            if response.status_code >= 300:
                actions.append(
                    {
                        "kind": "secrets",
                        "name": "GitHub",
                        "outcome": "failed",
                        "detail": _refusal(response),
                    }
                )
            else:
                for result in response.json().get("results") or []:
                    actions.append(
                        {
                            "kind": "secrets",
                            "name": str(
                                result.get("full_name") or result.get("repository_id")
                            ),
                            "outcome": "written"
                            if result.get("status") == "written"
                            else "skipped",
                            "detail": str(result.get("reason") or ""),
                        }
                    )

    if ci:
        known = [
            str(name) for name in (state.get("facts") or {}).get("environments") or []
        ]
        # In a dry run the environments this run would create count as known.
        known += [name for name in names if name not in known] if dry_run else []
        target = ci_environment or (
            "production" if "production" in known else (known[0] if known else None)
        )
        rows, skipped = pull_request_repositories(state)
        actions += skipped
        if target is None:
            actions.append(
                {
                    "kind": "pull request",
                    "name": "GitHub",
                    "outcome": "failed",
                    "detail": "the workspace has no environment to ask about: add --environments production, "
                    "or name one with --ci-environment",
                }
            )
        elif not rows:
            reason = (state.get("github") or {}).get(
                "reason"
            ) or "no registered GitHub repository belongs to a pacticipant"
            actions.append(
                {
                    "kind": "pull request",
                    "name": "GitHub",
                    "outcome": "skipped",
                    "detail": str(reason),
                }
            )
        else:
            linked = bool((state.get("github") or {}).get("linked"))
            response = conn.client.post_raw(
                conn.api_path(f"{_SETUP}/github/pull-requests", command=_COMMAND),
                json={
                    "repositories": rows,
                    "environment": target,
                    "preview": dry_run or not linked,
                },
            )
            if response.status_code >= 300:
                actions.append(
                    {
                        "kind": "pull request",
                        "name": "GitHub",
                        "outcome": "failed",
                        "detail": _refusal(response),
                    }
                )
            else:
                pull_requests = list(response.json().get("results") or [])
                for result in pull_requests:
                    status = str(result.get("status"))
                    outcome = {
                        "opened": "opened",
                        "exists": "exists",
                        "preview": "would" if dry_run else "skipped",
                    }.get(status, "skipped")
                    detail = str(result.get("url") or result.get("reason") or "")
                    if status == "preview" and not dry_run:
                        detail = (
                            str(
                                (state.get("github") or {}).get("reason")
                                or "no linked GitHub account"
                            )
                            + " The workflow is printed below."
                        )
                    actions.append(
                        {
                            "kind": "pull request",
                            "name": str(
                                result.get("full_name") or result.get("repository_id")
                            ),
                            "outcome": outcome,
                            "detail": detail,
                        }
                    )

    changed = any(
        action["outcome"] in ("created", "written", "opened") for action in actions
    )
    if changed:
        state = _read(conn)
    payload = {
        "setup": state,
        "actions": actions,
        "pull_requests": pull_requests,
        "dry_run": dry_run,
    }
    _emit(fmt, payload, setup_lines(state, actions, pull_requests, fmt))
    if any(action["outcome"] == "failed" for action in actions):
        raise click.exceptions.Exit(EXIT_ERROR)
