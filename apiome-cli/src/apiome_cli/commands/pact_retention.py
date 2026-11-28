"""``apiome pact retention show|set|preview`` — the Contracts clean-up rules, PFX-8.14 (#7311).

The same rules the Contracts **Settings → Clean-up** tab edits (``/v1/tenants/{t}/pact-retention/policy``):

* ``show`` — what is kept, whether the nightly clean-up runs, how long deleted items stay restorable,
  and what the last run did (``pacts:view``);
* ``set`` — change only the rules given; the rest stay as saved (``pacts:delete``). Every version
  deployed or released anywhere is always kept — there is no flag to turn that off;
* ``preview`` — what the rules would remove if the clean-up ran now: the same plan the nightly run
  applies. With rule flags it previews them without saving (``pacts:view``).

Like the rest of ``apiome pact`` the address and key come from ``PACT_BROKER_BASE_URL`` /
``PACT_BROKER_TOKEN`` (or ``-b`` / ``-k``) and any failure exits 1 with the server's message.
"""

from __future__ import annotations

from typing import Any, Optional

import typer

from apiome_cli.client.pact_broker_connection import BrokerConnection, connect
from apiome_cli.commands.pact_broker import BROKER_BASE_URL, BROKER_TOKEN, OUTPUT, _emit, _format
from apiome_cli.pact_retention_output import policy_lines, preview_lines

__all__ = ["RULE_FIELDS", "app", "merge_rules"]

app = typer.Typer(
    name="retention",
    help="Contracts clean-up rules: show them, change them, preview what they remove.",
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)

#: The fields ``PUT …/pact-retention/policy`` takes (all of them: a PUT replaces every rule).
RULE_FIELDS = (
    "keep_main_branch_latest",
    "keep_other_branch_latest",
    "keep_other_branch_days",
    "keep_tags",
    "nightly_enabled",
    "restore_window_days",
)

MAIN_LATEST = typer.Option(
    None, "--main-branch-latest", min=0, max=1000, help="Keep the latest N versions of each main branch (0: no such rule)."
)
OTHER_LATEST = typer.Option(
    None, "--other-branch-latest", min=0, max=1000, help="Keep the latest N versions of every other branch (0: no such rule)."
)
OTHER_DAYS = typer.Option(
    None,
    "--other-branch-days",
    min=0,
    max=3650,
    help="With --other-branch-latest: only while recorded in the last D days (0: however old).",
)
KEEP_TAG = typer.Option(
    None, "--keep-tag", help="Keep every version with this tag (repeat for several; replaces the saved tags)."
)
NO_TAGS = typer.Option(False, "--no-tags", help="Keep nothing by tag (clears the saved tags).")
NIGHTLY = typer.Option(None, "--nightly/--no-nightly", help="Run the clean-up every night after 02:00 UTC, or not.")
RESTORE_DAYS = typer.Option(
    None, "--restore-days", min=1, max=365, help="Days a deleted pacticipant or version stays restorable."
)

_POLICY = "/pact-retention/policy"


def merge_rules(
    current: dict[str, Any],
    *,
    main_branch_latest: Optional[int] = None,
    other_branch_latest: Optional[int] = None,
    other_branch_days: Optional[int] = None,
    keep_tags: Optional[list[str]] = None,
    no_tags: bool = False,
    nightly: Optional[bool] = None,
    restore_days: Optional[int] = None,
) -> tuple[dict[str, Any], bool]:
    """The rules to send: the saved ones with the given flags applied.

    Args:
        current: The saved policy (``GET …/pact-retention/policy``).
        main_branch_latest: ``--main-branch-latest``; 0 removes the rule.
        other_branch_latest: ``--other-branch-latest``; 0 removes the rule (and its age).
        other_branch_days: ``--other-branch-days``; 0 removes the age limit.
        keep_tags: ``--keep-tag`` values; replace the saved tags.
        no_tags: ``--no-tags``.
        nightly: ``--nightly`` / ``--no-nightly``.
        restore_days: ``--restore-days``.

    Returns:
        The rules body, and whether any flag changed something.

    Raises:
        ValueError: ``--keep-tag`` with ``--no-tags``; ``--other-branch-days`` without an other-branch
            count; a blank or repeated tag. Nothing is dropped silently.
    """
    rules = {field: current.get(field) for field in RULE_FIELDS}
    rules["keep_tags"] = list(current.get("keep_tags") or [])
    rules["nightly_enabled"] = bool(current.get("nightly_enabled"))
    changed = False
    if keep_tags and no_tags:
        raise ValueError("--keep-tag and --no-tags contradict each other; give one")
    if main_branch_latest is not None:
        rules["keep_main_branch_latest"] = main_branch_latest or None
        changed = True
    if other_branch_latest is not None:
        rules["keep_other_branch_latest"] = other_branch_latest or None
        if not other_branch_latest:
            rules["keep_other_branch_days"] = None
        changed = True
    if other_branch_days is not None:
        if other_branch_days and not rules["keep_other_branch_latest"]:
            raise ValueError("--other-branch-days needs an other-branch rule: add --other-branch-latest N")
        rules["keep_other_branch_days"] = other_branch_days or None
        changed = True
    if keep_tags:
        cleaned = [tag.strip() for tag in keep_tags]
        if any(not tag for tag in cleaned):
            raise ValueError("--keep-tag needs a tag name")
        repeated = sorted({tag for tag in cleaned if cleaned.count(tag) > 1})
        if repeated:
            raise ValueError(f"tag given more than once: {', '.join(repeated)}")
        rules["keep_tags"] = cleaned
        changed = True
    if no_tags:
        rules["keep_tags"] = []
        changed = True
    if nightly is not None:
        rules["nightly_enabled"] = nightly
        changed = True
    if restore_days is not None:
        rules["restore_window_days"] = restore_days
        changed = True
    return rules, changed


def _connection(ctx: typer.Context, broker_base_url: Optional[str], broker_token: Optional[str]) -> BrokerConnection:
    """The workspace connection (``pact`` group options)."""
    return connect(ctx, broker_base_url=broker_base_url, broker_token=broker_token)


def _saved(conn: BrokerConnection, command: str) -> dict[str, Any]:
    """The saved policy."""
    return conn.client.get(conn.api_path(_POLICY, command=command)).json()


@app.command("show")
def show(
    ctx: typer.Context,
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Show the clean-up rules, the nightly switch and the restore window (GET …/pact-retention/policy).

    Needs pacts:view. Exits 1 on any refusal.
    """
    fmt = _format(ctx, output)
    policy = _saved(_connection(ctx, broker_base_url, broker_token), "retention show")
    _emit(fmt, policy, policy_lines(policy, fmt))


@app.command("set")
def set_rules(
    ctx: typer.Context,
    main_branch_latest: Optional[int] = MAIN_LATEST,
    other_branch_latest: Optional[int] = OTHER_LATEST,
    other_branch_days: Optional[int] = OTHER_DAYS,
    keep_tag: Optional[list[str]] = KEEP_TAG,
    no_tags: bool = NO_TAGS,
    nightly: Optional[bool] = NIGHTLY,
    restore_days: Optional[int] = RESTORE_DAYS,
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Change the clean-up rules; the ones not given stay as saved (PUT …/pact-retention/policy).

    Deployed and released versions are always kept. Run `apiome pact retention preview` with the
    same flags first to see what the rules remove. Needs pacts:delete. Exits 1 on any refusal.
    """
    fmt = _format(ctx, output)
    conn = _connection(ctx, broker_base_url, broker_token)
    try:
        rules, changed = merge_rules(
            _saved(conn, "retention set"),
            main_branch_latest=main_branch_latest,
            other_branch_latest=other_branch_latest,
            other_branch_days=other_branch_days,
            keep_tags=keep_tag,
            no_tags=no_tags,
            nightly=nightly,
            restore_days=restore_days,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not changed:
        raise typer.BadParameter(
            "nothing to change: give a rule flag, --nightly / --no-nightly or --restore-days (see --help)"
        )
    policy = conn.client.put(conn.api_path(_POLICY, command="retention set"), json=rules).json()
    _emit(fmt, policy, policy_lines(policy, fmt, saved=True))


@app.command("preview")
def preview(
    ctx: typer.Context,
    main_branch_latest: Optional[int] = MAIN_LATEST,
    other_branch_latest: Optional[int] = OTHER_LATEST,
    other_branch_days: Optional[int] = OTHER_DAYS,
    keep_tag: Optional[list[str]] = KEEP_TAG,
    no_tags: bool = NO_TAGS,
    nightly: Optional[bool] = NIGHTLY,
    restore_days: Optional[int] = RESTORE_DAYS,
    output: str = OUTPUT,
    broker_base_url: Optional[str] = BROKER_BASE_URL,
    broker_token: Optional[str] = BROKER_TOKEN,
) -> None:
    """Preview what the clean-up rules remove if they ran now (POST …/pact-retention/policy/preview).

    Without flags it previews the saved rules — exactly what the next nightly run removes. With
    rule flags it previews the saved rules changed by them, without saving. Needs pacts:view.
    """
    fmt = _format(ctx, output)
    conn = _connection(ctx, broker_base_url, broker_token)
    try:
        rules, changed = merge_rules(
            _saved(conn, "retention preview"),
            main_branch_latest=main_branch_latest,
            other_branch_latest=other_branch_latest,
            other_branch_days=other_branch_days,
            keep_tags=keep_tag,
            no_tags=no_tags,
            nightly=nightly,
            restore_days=restore_days,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    body = {"rules": rules} if changed else {}
    document = conn.client.post(conn.api_path(f"{_POLICY}/preview", command="retention preview"), json=body).json()
    _emit(fmt, document, preview_lines(document, fmt))
