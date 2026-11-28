"""The committed ``apiome pact`` command list stays in step with the CLI (PFX-8.2, #7299).

``apiome-cli/pact-commands.json`` is what the UI's parity gate reads; if it were stale, a new
command could ship without a ledger row and nothing would notice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from apiome_cli.pact_command_list import (
    PACT_COMMANDS_FILE,
    REGENERATE_COMMAND,
    pact_commands,
    render_pact_commands,
)

MONOREPO = Path(__file__).resolve().parents[2]


def test_the_committed_list_matches_the_cli() -> None:
    committed = (MONOREPO / PACT_COMMANDS_FILE).read_text(encoding="utf-8")
    assert (
        committed == render_pact_commands()
    ), f"stale: regenerate with `{REGENERATE_COMMAND}`"


def test_every_registered_pact_command_is_listed() -> None:
    from apiome_cli.commands import pact, pact_broker

    names = {entry["name"] for entry in pact_commands()}
    registered = {name for name, _ in pact_broker.COMMANDS}
    registered |= {
        command.name for command in pact.app.registered_commands if command.name
    }
    assert names == registered
    assert len(names) == 23


def test_an_entry_names_its_arguments_and_long_flags_but_not_help() -> None:
    entry = next(e for e in pact_commands() if e["name"] == "create-webhook")
    assert entry["arguments"] == ["url"]
    assert entry["options"][:3] == ["--request", "--header", "--data"]
    assert "--help" not in entry["options"]
    assert entry["summary"].startswith("Create a webhook")


def test_the_list_is_sorted_and_the_file_is_stable_json() -> None:
    document = json.loads(render_pact_commands())
    names = [entry["name"] for entry in document["commands"]]
    assert names == sorted(names)
    assert document["group"] == "apiome pact"
    assert render_pact_commands().endswith("}\n")


def test_hidden_commands_and_options_are_left_out() -> None:
    root = typer.Typer()
    group = typer.Typer()

    @group.command("shown")
    def shown(
        name: str = typer.Argument(...),
        flag: bool = typer.Option(False, "--flag"),
        quiet: bool = typer.Option(False, "-q"),
        secret: str = typer.Option("", "--secret", hidden=True),
    ) -> None:
        """Shown. More words."""

    @group.command("hidden", hidden=True)
    def hidden() -> None:
        """Hidden."""

    root.add_typer(group, name="pact")
    assert pact_commands(root) == [
        {
            "name": "shown",
            "summary": "Shown.",
            "arguments": ["name"],
            "options": ["--flag", "-q"],
        }
    ]


def test_an_app_without_a_pact_group_is_refused() -> None:
    root = typer.Typer()

    @root.command("other")
    def other() -> None:
        """Other."""

    @root.command("more")
    def more() -> None:
        """More."""

    with pytest.raises(LookupError, match="no `pact` command group"):
        pact_commands(root)
