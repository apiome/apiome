"""Tests for the generated CLI reference pages (DOCS-1.11, #5628).

The first test is the **drift gate**: it renders every page in memory and compares it with the
committed copy under ``apiome-docs/docs/reference/cli/``. Adding a command or an option without
regenerating the reference turns CI red.

The rest render a small Typer app and check the page says true things: nested groups get a
section each, the options table carries type / default / required / help, hidden commands and
options stay out, table cells are escaped, and a default is never read from the environment.
"""

from __future__ import annotations

import importlib.util
from enum import Enum
from pathlib import Path
from typing import Annotated

import click
import pytest
import typer

from apiome_cli.reference_doc import (
    CLI_REFERENCE_DIR,
    MAX_DESCRIPTION_WORDS,
    REGENERATE_COMMAND,
    cell,
    clean_help,
    collect_exit_codes,
    describe,
    prose,
    render_cli_reference,
    render_exit_codes_page,
    root_command,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / CLI_REFERENCE_DIR
SCRIPT = REPO_ROOT / "apiome-cli" / "scripts" / "generate_cli_reference_docs.py"


# ===========================================================================
# The drift gate
# ===========================================================================


def test_committed_reference_matches_the_command_tree() -> None:
    """Every committed page equals a fresh render, and no stray page is left behind."""
    pages = render_cli_reference()
    committed = {path.name for path in REFERENCE_DIR.iterdir() if path.is_file()}
    assert committed == set(pages), (
        f"{CLI_REFERENCE_DIR} has the wrong files. Regenerate with: {REGENERATE_COMMAND}"
    )
    stale = [
        name
        for name, content in pages.items()
        if (REFERENCE_DIR / name).read_text(encoding="utf-8") != content
    ]
    assert not stale, (
        f"Stale CLI reference pages: {', '.join(stale)}. Regenerate with: {REGENERATE_COMMAND}"
    )


def test_every_top_level_command_has_a_page_and_every_command_a_section() -> None:
    """The acceptance rule: each command reaches the reference."""
    pages = render_cli_reference()
    root = root_command()
    for name, command in root.commands.items():
        if command.hidden:
            continue
        page = pages[f"{name}.md"]
        assert f"## apiome {name} {{#{name}}}" in page
        if isinstance(command, click.Group):
            for sub_name, sub in command.commands.items():
                if not sub.hidden:
                    assert f"{{#{name}-{sub_name}}}" in page, f"{name} {sub_name}"


def test_descriptions_fit_the_docs_gate() -> None:
    """The docs gate rejects a description over 14 words."""
    for name, content in render_cli_reference().items():
        if not name.endswith((".md", ".mdx")):
            continue
        line = next(
            line for line in content.splitlines() if line.startswith("description:")
        )
        assert (
            len(line.split(":", 1)[1].strip().strip('"').split())
            <= MAX_DESCRIPTION_WORDS
        ), name


def test_script_check_mode_reports_a_stale_folder(tmp_path: Path) -> None:
    """``--check`` names missing, stale and extra files."""
    spec = importlib.util.spec_from_file_location("generate_cli_reference_docs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    (tmp_path / "a.md").write_text("old", encoding="utf-8")
    (tmp_path / "stray.md").write_text("x", encoding="utf-8")
    problems = module.compare(tmp_path, {"a.md": "new", "b.md": "b"})
    assert problems == ["stale:   a.md", "missing: b.md", "extra:   stray.md"]
    (tmp_path / "a.md").write_text("new", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "stray.md").unlink()
    assert module.compare(tmp_path, {"a.md": "new", "b.md": "b"}) == []


# ===========================================================================
# Rendering a small app
# ===========================================================================


class Format(str, Enum):
    """Output formats for the sample app."""

    json = "json"
    yaml = "yaml"


def sample_app() -> typer.Typer:
    """A tiny CLI: a nested group, every option shape, and hidden parts.

    :returns: The Typer app.
    """
    app = typer.Typer(name="apiome", help="Sample CLI.")
    things = typer.Typer(help="Manage things.")
    deep = typer.Typer(help="Deeper things.")
    app.add_typer(things, name="things")
    things.add_typer(deep, name="deep")

    @things.command("list")
    def list_things(
        limit: Annotated[int, typer.Option(help="How many | at most.")] = 20,
        fmt: Annotated[
            Format, typer.Option("--format", help="Output format.")
        ] = Format.json,
        token: Annotated[
            str | None, typer.Option(envvar="SAMPLE_TOKEN", help="Token for <tenant>.")
        ] = None,
        verbose: Annotated[
            bool, typer.Option("--verbose/--quiet", help="Talk more.")
        ] = False,
        secret: Annotated[str, typer.Option(hidden=True)] = "s3cr3t",
    ) -> None:
        """List things.

        Shows every thing in the `<tenant>`.
        """

    @things.command("rm", hidden=True)
    def remove() -> None:
        """Hidden command."""

    @deep.command("dig")
    def dig(target: Annotated[str, typer.Argument(help="Where to dig.")]) -> None:
        """Dig deep."""

    @app.command("ping")
    def ping() -> None:
        """Ping the service."""

    return app


@pytest.fixture()
def pages(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The sample app's pages, rendered with ``SAMPLE_TOKEN`` set in the environment."""
    monkeypatch.setenv("SAMPLE_TOKEN", "leaked-token-value")
    return render_cli_reference(sample_app(), exit_codes_source="EXIT_SUCCESS = 0\n")


def test_one_page_per_top_level_command_and_an_index(pages: dict[str, str]) -> None:
    assert set(pages) == {
        "_category_.json",
        "index.mdx",
        "things.md",
        "ping.md",
        "exit-codes.md",
    }
    assert "[`apiome things`](./things.md) | Manage things." in pages["index.mdx"]
    # The index is MDX, which reads `{#id}` as an expression; the automatic id is the same.
    assert "\n## Global options\n" in pages["index.mdx"]


def test_nested_groups_get_a_section_each(pages: dict[str, str]) -> None:
    page = pages["things.md"]
    for heading in (
        "## apiome things {#things}",
        "## apiome things deep {#things-deep}",
        "## apiome things deep dig {#things-deep-dig}",
        "## apiome things list {#things-list}",
    ):
        assert heading in page
    assert "Subcommands: [`deep`](#things-deep), [`list`](#things-list)." in page
    assert "```text\napiome things deep dig [OPTIONS] TARGET\n```" in page


def test_options_table_has_type_default_required_and_help(
    pages: dict[str, str],
) -> None:
    page = pages["things.md"]
    assert "| `--limit` | integer | `20` |  | How many \\| at most. |" in page
    assert "| `--format` | `json` \\| `yaml` | `json` |  | Output format. |" in page
    assert "| `--verbose` / `--quiet` | flag | `--quiet` |  | Talk more. |" in page
    assert "| `TARGET` | text | yes | Where to dig. |" in page


def test_hidden_commands_and_options_are_left_out(pages: dict[str, str]) -> None:
    page = pages["things.md"]
    assert "things rm" not in page
    assert "--secret" not in page and "s3cr3t" not in page


def test_environment_values_never_leak(pages: dict[str, str]) -> None:
    """An option's environment variable is named; its value is not."""
    page = pages["things.md"]
    assert "leaked-token-value" not in page
    assert "Token for &lt;tenant&gt;. Env: `SAMPLE_TOKEN`." in page


def test_help_keeps_code_spans_and_escapes_html_outside_them(
    pages: dict[str, str],
) -> None:
    assert "Shows every thing in the `<tenant>`." in pages["things.md"]


# ===========================================================================
# Helpers
# ===========================================================================


def test_clean_help_drops_click_markers_and_rich_markup() -> None:
    assert clean_help("Do [bold]it[/bold].\n\b\nkept\f\nhidden tail") == "Do it.\nkept"
    assert clean_help(None) == ""


def test_cell_is_one_escaped_line() -> None:
    assert cell("a | b\n  c <d> `<e>`") == "a \\| b c &lt;d&gt; `<e>`"


def test_prose_keeps_indented_examples_verbatim() -> None:
    rendered = prose("Run it:\n\n  apiome ping\n  apiome ping --json")
    assert rendered == "Run it:\n\n```text\napiome ping\napiome ping --json\n```"


def test_describe_is_one_short_sentence() -> None:
    assert (
        describe("List versions (GET /v1/versions). More text.", "x")
        == "List versions."
    )
    long = " ".join(["word"] * 30)
    assert len(describe(long, "x").split()) <= MAX_DESCRIPTION_WORDS
    assert describe("", "The apiome ping command.") == "The apiome ping command."


def test_exit_codes_come_from_the_module_comments() -> None:
    source = (
        '"""Exit codes.\n\nUse ``EXIT_USAGE`` for :data:`bad` input."""\n'
        "#: All good.\nEXIT_SUCCESS = 0\n\n"
        "#: Bad usage,\n#: or a 4xx.\nEXIT_USAGE = 2\n"
        "NOT_A_CODE = 9\n"
    )
    docstring, codes = collect_exit_codes(source)
    assert docstring.startswith("Exit codes.")
    assert [(code.code, code.name, code.meaning) for code in codes] == [
        (0, "EXIT_SUCCESS", "All good."),
        (2, "EXIT_USAGE", "Bad usage, or a 4xx."),
    ]
    page = render_exit_codes_page(source)
    assert "| `2` | `EXIT_USAGE` | Bad usage, or a 4xx. |" in page
    assert "Use `EXIT_USAGE` for `bad` input." in page


def test_real_exit_codes_are_all_documented() -> None:
    from apiome_cli import exit_codes

    _, codes = collect_exit_codes()
    names = {name for name in vars(exit_codes) if name.startswith("EXIT_")}
    assert {code.name for code in codes} == names
    assert all(code.meaning for code in codes)
