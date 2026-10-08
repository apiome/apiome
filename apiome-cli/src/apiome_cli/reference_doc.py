"""Generate the CLI reference pages of the documentation site (DOCS-1.11, #5628).

The pages under ``apiome-docs/docs/reference/cli/`` are rendered from the command tree itself —
the Click command Typer builds from :data:`apiome_cli.main.app` — and from
:mod:`apiome_cli.exit_codes`, so the reference cannot drift from the code:
``tests/test_cli_reference_docs.py`` renders them in memory and compares them with the committed
files, and ``scripts/generate_cli_reference_docs.py --check`` does the same in CI.

What is written:

- ``index.mdx`` — the root command's global options and a table of every top-level command;
- ``<command>.md`` — one page per top-level command, with a section for the command and for every
  nested subcommand (help, usage, arguments, options);
- ``exit-codes.md`` — every ``EXIT_*`` constant with its documented meaning.

Command pages are CommonMark (``.md``): Docusaurus reads them with ``markdown.format: detect``, so
help text containing ``{`` needs no MDX escaping. Raw HTML is dropped by CommonMark, so ``<`` and
``>`` outside code spans are written as entities.

Output is deterministic: commands, options and pages are ordered by name, and a default is shown
only when it is a literal from the code — never a value read from the environment (an option's
environment variable is named instead).
"""

from __future__ import annotations

import ast
import enum
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from typer.main import get_command

if TYPE_CHECKING:
    import typer

#: Where the pages live, relative to the monorepo root.
CLI_REFERENCE_DIR = Path("apiome-docs/docs/reference/cli")

#: The script that writes them, relative to the monorepo root (recorded in each page).
GENERATOR = "apiome-cli/scripts/generate_cli_reference_docs.py"

#: How to regenerate the pages, quoted in the stale-page message.
REGENERATE_COMMAND = (
    "cd apiome-cli && uv run python scripts/generate_cli_reference_docs.py"
)

#: The program name readers type.
PROGRAM = "apiome"

#: The longest front-matter description the docs gate accepts, in words.
MAX_DESCRIPTION_WORDS = 14

#: Rich console markup Typer would render as styling, e.g. ``[bold]`` or ``[/]``.
_RICH_MARKUP = re.compile(
    r"\[/?(?:bold|dim|italic|underline|strike|reverse|blink|"
    r"red|green|yellow|blue|magenta|cyan|white|black|"
    r"bright_[a-z]+|link(?:=[^\]]*)?)?\]"
)

#: A backtick code span, which must not have its ``<`` / ``>`` escaped.
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def clean_help(text: str | None) -> str:
    """Normalise a command's or parameter's help text for the page.

    Applies Click's conventions — everything after a ``\\f`` is dropped, and a line holding only
    ``\\b`` (Click's "do not rewrap" marker) is removed — then dedents and strips Rich markup.

    :param text: Raw help, a docstring or ``None``.
    :returns: The cleaned help, or ``""``.
    """
    if not text:
        return ""
    text = text.split("\f", 1)[0]
    text = inspect.cleandoc(text)
    lines = [line for line in text.splitlines() if line.strip() != "\b"]
    return _RICH_MARKUP.sub("", "\n".join(lines)).strip()


def first_line(text: str | None) -> str:
    """The first line of cleaned help text.

    :param text: Raw help.
    :returns: Its first non-empty line, or ``""``.
    """
    cleaned = clean_help(text)
    return cleaned.splitlines()[0].strip() if cleaned else ""


def _escape_html(text: str) -> str:
    """Escape ``<``, ``>`` and ``&`` outside backtick code spans.

    CommonMark drops raw HTML, so an ``<id>`` placeholder in help text would vanish; inside a code
    span it is literal, and an entity there would show as ``&lt;``.

    :param text: Markdown text.
    :returns: The text with angle brackets outside code spans written as entities.
    """
    out: list[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        out.append(_entities(text[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(_entities(text[last:]))
    return "".join(out)


def _entities(text: str) -> str:
    """Replace ``&``, ``<`` and ``>`` with HTML entities.

    :param text: Plain text.
    :returns: The escaped text.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cell(text: str | None) -> str:
    """Make text safe for one Markdown table cell.

    :param text: Any text.
    :returns: One line, with ``|`` escaped and angle brackets outside code spans as entities.
    """
    if not text:
        return ""
    one_line = " ".join(text.split())
    return _escape_html(one_line).replace("|", "\\|")


def prose(text: str) -> str:
    """Render cleaned help text as Markdown blocks.

    Blank-line separated blocks become paragraphs, except a block with an indented line (an
    example or an aligned list), which is kept verbatim in a code block.

    :param text: Cleaned help text.
    :returns: Markdown, or ``""``.
    """
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.rstrip().splitlines()
        if not lines or not block.strip():
            continue
        if any(line.startswith((" ", "\t")) for line in lines[1:]) or lines[
            0
        ].startswith((" ", "\t")):
            body = inspect.cleandoc("\n".join(lines))
            blocks.append(f"```text\n{body}\n```")
        else:
            blocks.append(_escape_html(" ".join(line.strip() for line in lines)))
    return "\n\n".join(blocks)


def first_sentence(text: str | None) -> str:
    """The first sentence of a command's help — what a one-line summary shows.

    :param text: Raw help.
    :returns: The first sentence of the first line, or ``""``.
    """
    line = first_line(text)
    return re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0] if line else ""


def describe(text: str, fallback: str) -> str:
    """A front-matter description: one sentence of at most :data:`MAX_DESCRIPTION_WORDS` words.

    :param text: The command's first help line.
    :param fallback: Used when the command has no help.
    :returns: The description, sentence case, ending in a full stop.
    """
    sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0] if text else ""
    sentence = re.sub(
        r"\s*\([^)]*\)", "", sentence
    )  # "(GET /v1/…)" is detail, not summary
    words = (
        sentence.rstrip(".").replace("`", "").split() or fallback.rstrip(".").split()
    )
    if len(words) > MAX_DESCRIPTION_WORDS:
        words = words[:MAX_DESCRIPTION_WORDS]
        while words and words[-1].lower() in {
            "a",
            "an",
            "and",
            "or",
            "the",
            "of",
            "to",
            "for",
        }:
            words.pop()
    result = " ".join(words).rstrip(",;:")
    return result[:1].upper() + result[1:] + "."


def _front_matter(fields: dict[str, Any]) -> str:
    """YAML front matter; strings are JSON-quoted, which YAML reads as plain strings.

    :param fields: Ordered fields.
    :returns: The ``---`` block, ending in a newline.
    """
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(value)}]")
        elif isinstance(value, str):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The command tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandNode:
    """One visible command and the Click context it runs in.

    :ivar path: Names from the program down, e.g. ``("apiome", "versions", "list")``.
    :ivar command: The Click command.
    :ivar ctx: A context chain matching ``path``, used to build the usage line.
    """

    path: tuple[str, ...]
    command: click.Command
    ctx: click.Context

    @property
    def anchor(self) -> str:
        """Heading id: the names after the program, joined by hyphens."""
        return "-".join(self.path[1:]) or PROGRAM

    @property
    def display(self) -> str:
        """The command as typed, e.g. ``apiome versions list``."""
        return " ".join(self.path)


def root_command(app: typer.Typer | None = None) -> click.Group:
    """The Click group Typer builds for the CLI.

    :param app: A Typer app; defaults to :data:`apiome_cli.main.app`.
    :returns: The root group.
    :raises TypeError: When the app is not a group (it always is for ``apiome``).
    """
    if app is None:
        from apiome_cli.main import app as root_app

        app = root_app
    root = get_command(app)
    if not isinstance(root, click.Group):
        raise TypeError("the CLI root is not a command group")
    return root


def walk(command: click.Command, ctx: click.Context) -> list[CommandNode]:
    """Every visible command under ``command``, depth first, siblings by name.

    :param command: The command to start from (included).
    :param ctx: Its context.
    :returns: The command and its visible descendants.
    """
    path = tuple(ctx.command_path.split())
    nodes = [CommandNode(path=path, command=command, ctx=ctx)]
    if isinstance(command, click.Group):
        for name in sorted(command.commands):
            sub = command.commands[name]
            if sub.hidden:
                continue
            sub_ctx = click.Context(sub, info_name=name, parent=ctx)
            nodes.extend(walk(sub, sub_ctx))
    return nodes


def top_level(root: click.Group) -> list[tuple[str, click.Command]]:
    """The visible top-level commands, by name.

    :param root: The root group.
    :returns: ``(name, command)`` pairs.
    """
    return [
        (name, root.commands[name])
        for name in sorted(root.commands)
        if not root.commands[name].hidden
    ]


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


def _visible_params(
    command: click.Command, kind: type[click.Parameter]
) -> list[click.Parameter]:
    """The command's parameters of one kind, hidden ones left out.

    :param command: The command.
    :param kind: :class:`click.Option` or :class:`click.Argument`.
    :returns: The parameters, in declaration order.
    """
    return [
        p
        for p in command.params
        if isinstance(p, kind) and not getattr(p, "hidden", False)
    ]


def _type_label(param: click.Parameter) -> str:
    """A short type label: the choices, ``flag``, or the Click type name.

    :param param: The parameter.
    :returns: e.g. ``json | yaml``, ``flag``, ``integer``.
    """
    if isinstance(param, click.Option) and param.is_flag:
        return "flag"
    if isinstance(param.type, click.Choice):
        label = " \\| ".join(f"`{choice}`" for choice in param.type.choices)
    else:
        label = param.type.name
    if param.multiple or (param.nargs not in (1, -1) and param.nargs > 1):
        label += " (repeatable)" if param.multiple else f" ×{param.nargs}"
    return label


def _literal(value: Any) -> str | None:
    """Render a default as text, or ``None`` when it should not be shown.

    :param value: A parameter's default.
    :returns: The text, or ``None`` for an empty, dynamic or non-literal default.
    """
    if value is None or callable(value):
        return None
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        return ", ".join(str(item) for item in value)
    if isinstance(value, (str, int, float, Path)):
        return str(value)
    return None


def default_label(param: click.Parameter) -> str:
    """The default shown in the options table, following Click's ``show_default`` rules.

    A default is shown only when it is a literal written in the code: not ``None``, not a
    callable, not for a hidden-input (secret) option, and not when ``show_default`` is off. A plain
    on/off flag shows nothing when it is off by default. ``show_default`` set to a string shows that
    string, as Click does.

    :param param: The parameter.
    :returns: The default as Markdown, or ``""``.
    """
    show = getattr(param, "show_default", None)
    if show is False:
        return ""
    if isinstance(show, str) and show:
        return cell(show)
    if isinstance(param, click.Option):
        if param.hide_input:
            return ""
        if param.is_flag:
            if param.secondary_opts:
                return (
                    f"`{param.opts[-1] if param.default else param.secondary_opts[-1]}`"
                )
            return "on" if param.default is True else ""
    literal = _literal(param.default)
    return f"`{literal}`" if literal not in (None, "") else ""


def _envvar_note(param: click.Parameter) -> str:
    """Name the option's environment variable(s) — never their value.

    :param param: The parameter.
    :returns: e.g. ``Env: `APIOME_TOKEN`.``, or ``""``.
    """
    envvar = getattr(param, "envvar", None)
    if not envvar:
        return ""
    names = [envvar] if isinstance(envvar, str) else list(envvar)
    return "Env: " + ", ".join(f"`{name}`" for name in names) + "."


def options_table(command: click.Command) -> str:
    """The command's options as a Markdown table.

    :param command: The command.
    :returns: The table, or ``""`` when the command has no visible options.
    """
    rows = [
        "| Option | Type | Default | Required | Description |",
        "| --- | --- | --- | --- | --- |",
    ]
    for option in _visible_params(command, click.Option):
        assert isinstance(option, click.Option)
        names = ", ".join(f"`{name}`" for name in option.opts)
        if option.secondary_opts:
            names += " / " + ", ".join(f"`{name}`" for name in option.secondary_opts)
        help_text = cell(clean_help(option.help))
        notes = " ".join(
            part
            for part in (
                help_text,
                _envvar_note(option),
                "**Deprecated.**" if getattr(option, "deprecated", False) else "",
            )
            if part
        )
        rows.append(
            f"| {names} | {_type_label(option)} | {default_label(option)} "
            f"| {'yes' if option.required else ''} | {notes} |"
        )
    return "\n".join(rows) if len(rows) > 2 else ""


def arguments_table(command: click.Command) -> str:
    """The command's positional arguments as a Markdown table.

    :param command: The command.
    :returns: The table, or ``""`` when it takes none.
    """
    rows = ["| Argument | Type | Required | Description |", "| --- | --- | --- | --- |"]
    for argument in _visible_params(command, click.Argument):
        name = (argument.name or "").upper()
        if argument.nargs == -1:
            name += "..."
        rows.append(
            f"| `{name}` | {_type_label(argument)} | {'yes' if argument.required else ''} "
            f"| {cell(clean_help(getattr(argument, 'help', None)))} |"
        )
    return "\n".join(rows) if len(rows) > 2 else ""


def usage_line(node: CommandNode) -> str:
    """The command's usage, as Click prints it after ``Usage:``.

    :param node: The command.
    :returns: e.g. ``apiome versions list [OPTIONS]``.
    """
    pieces = node.command.collect_usage_pieces(node.ctx)
    return " ".join([node.display, *pieces])


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def render_section(node: CommandNode) -> str:
    """One command's section: heading, help, usage, arguments and options.

    :param node: The command.
    :returns: Markdown, ending in a newline.
    """
    parts = [f"## {node.display} {{#{node.anchor}}}"]
    if node.command.deprecated:
        parts.append("**Deprecated.**")
    help_md = prose(clean_help(node.command.help))
    if help_md:
        parts.append(help_md)
    parts.append(f"```text\n{usage_line(node)}\n```")
    if isinstance(node.command, click.Group) and node.command.commands:
        subs = [
            f"[`{name}`](#{node.anchor}-{name})"
            for name in sorted(node.command.commands)
            if not node.command.commands[name].hidden
        ]
        if subs:
            parts.append("Subcommands: " + ", ".join(subs) + ".")
    arguments = arguments_table(node.command)
    if arguments:
        parts.append("**Arguments**\n\n" + arguments)
    options = options_table(node.command)
    if options:
        parts.append("**Options**\n\n" + options)
    return "\n\n".join(parts) + "\n"


def render_command_page(
    name: str, command: click.Command, root_ctx: click.Context, position: int
) -> str:
    """The page for one top-level command and everything under it.

    :param name: The command's name.
    :param command: The command.
    :param root_ctx: The root command's context.
    :param position: Sidebar position.
    :returns: The page.
    """
    ctx = click.Context(command, info_name=name, parent=root_ctx)
    nodes = walk(command, ctx)
    summary = first_line(command.help)
    header = _front_matter(
        {
            "title": f"{PROGRAM} {name}",
            "description": describe(summary, f"The {PROGRAM} {name} command."),
            "sidebar_position": position,
            "tags": ["cli", "reference"],
            "generated": GENERATOR,
        }
    )
    intro = (
        f"<!-- Generated by {GENERATOR} from the command tree. Do not edit; "
        f"regenerate with: {REGENERATE_COMMAND} -->\n\n"
        "Global options such as `--base-url`, `--tenant` and `--json` go before the command — "
        "see [CLI reference](./index.mdx#global-options). Exit codes are listed in "
        "[Exit codes](./exit-codes.md).\n"
    )
    return (
        header + "\n" + intro + "\n" + "\n".join(render_section(node) for node in nodes)
    )


def render_index(
    root: click.Group,
    root_ctx: click.Context,
    commands: list[tuple[str, click.Command]],
) -> str:
    """The CLI reference landing page (MDX): global options and the command table.

    :param root: The root group.
    :param root_ctx: Its context.
    :param commands: The visible top-level commands.
    :returns: The page.
    """
    header = _front_matter(
        {
            "title": "CLI reference",
            "description": "Every apiome command, option and exit code, generated from the CLI.",
            # The page sits in the docs site's CLI guide, after the quick-start.
            "sidebar_label": "Command reference",
            "sidebar_position": 1,
            "tags": ["cli", "reference"],
            "generated": GENERATOR,
        }
    )
    rows = ["| Command | What it does |", "| --- | --- |"]
    for name, command in commands:
        rows.append(
            f"| [`{PROGRAM} {name}`](./{name}.md) | {_mdx_cell(first_sentence(command.help))} |"
        )
    options = _mdx_cell_table(options_table(root))
    body = [
        f"{{/* Generated by {GENERATOR} from the command tree. Do not edit; regenerate with: "
        f"{REGENERATE_COMMAND} */}}",
        f"The `{PROGRAM}` command-line client talks to the Apiome REST API. This reference is "
        "generated from the CLI's own command tree, so it lists exactly what the installed version "
        f"accepts; `{PROGRAM} --help` and `{PROGRAM} help <command>` print the same help in a "
        "terminal. For a walkthrough, start with the [CLI quick-start](../cli-quickstart.md).",
        "## Usage",
        f"```text\n{' '.join([PROGRAM, *root.collect_usage_pieces(root_ctx)])}\n```",
        "## Global options",
        "Global options go before the command, e.g. "
        f"`{PROGRAM} --base-url http://localhost:8000 --json projects list`.",
        options,
        "## Commands",
        "\n".join(rows),
        "## Exit codes",
        "Every command exits `0` on success, `1` on an error and `2` on bad usage or a rejected "
        "request; the quality-gate and check commands add their own codes. See "
        "[Exit codes](./exit-codes.md).",
    ]
    return header + "\n" + "\n\n".join(body) + "\n"


def _mdx_cell(text: str) -> str:
    """A table cell for the MDX index page: also escapes MDX's ``{`` and ``}``.

    :param text: Any text.
    :returns: The cell.
    """
    return cell(text).replace("{", "\\{").replace("}", "\\}")


def _mdx_cell_table(table: str) -> str:
    """Escape MDX expression braces in a rendered table (outside code spans).

    :param table: A Markdown table built with :func:`cell`.
    :returns: The table, safe in MDX.
    """
    out: list[str] = []
    for line in table.splitlines():
        pieces: list[str] = []
        last = 0
        for match in _CODE_SPAN.finditer(line):
            pieces.append(
                line[last : match.start()].replace("{", "\\{").replace("}", "\\}")
            )
            pieces.append(match.group(0))
            last = match.end()
        pieces.append(line[last:].replace("{", "\\{").replace("}", "\\}"))
        out.append("".join(pieces))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExitCode:
    """One documented exit code.

    :ivar name: The constant, e.g. ``EXIT_USAGE``.
    :ivar code: Its value.
    :ivar meaning: The ``#:`` comment above it, as one paragraph.
    """

    name: str
    code: int
    meaning: str


def _rst_to_md(text: str) -> str:
    """Turn the reStructuredText roles used in the module into Markdown code spans.

    :param text: Text with ``:data:`X```, ``:mod:`m``` or double-backtick literals.
    :returns: Markdown text.
    """
    text = re.sub(r":[a-z]+:`~?([^`]+)`", r"`\1`", text)
    return text.replace("``", "`")


def collect_exit_codes(source: str | None = None) -> tuple[str, list[ExitCode]]:
    """Read the exit codes and their ``#:`` comments from :mod:`apiome_cli.exit_codes`.

    :param source: The module's source; read from the installed module when omitted.
    :returns: The module docstring and every ``EXIT_*`` constant, by value.
    """
    if source is None:
        from apiome_cli import exit_codes

        source = inspect.getsource(exit_codes)
    tree = ast.parse(source)
    lines = source.splitlines()
    codes: list[ExitCode] = []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id.startswith("EXIT_")):
            continue
        if not (
            isinstance(node.value, ast.Constant) and isinstance(node.value.value, int)
        ):
            continue
        comment: list[str] = []
        index = node.lineno - 2
        while index >= 0 and lines[index].lstrip().startswith("#:"):
            comment.insert(0, lines[index].lstrip()[2:].strip())
            index -= 1
        codes.append(ExitCode(target.id, node.value.value, " ".join(comment)))
    return ast.get_docstring(tree) or "", sorted(codes, key=lambda code: code.code)


def render_exit_codes_page(source: str | None = None, position: int = 1000) -> str:
    """The exit-codes page.

    :param source: The exit-codes module source (for tests); the real module when omitted.
    :param position: Sidebar position.
    :returns: The page.
    """
    docstring, codes = collect_exit_codes(source)
    header = _front_matter(
        {
            "title": "Exit codes",
            "description": "What each apiome exit code means, for scripts and CI pipelines.",
            "sidebar_position": position,
            "tags": ["cli", "reference"],
            "generated": GENERATOR,
        }
    )
    rows = ["| Code | Name | Meaning |", "| --- | --- | --- |"]
    for code in codes:
        rows.append(
            f"| `{code.code}` | `{code.name}` | {cell(_rst_to_md(code.meaning))} |"
        )
    intro = prose(_rst_to_md(clean_help(docstring)))
    return (
        header
        + "\n"
        + f"<!-- Generated by {GENERATOR} from apiome_cli/exit_codes.py. Do not edit. -->\n\n"
        + intro
        + "\n\n"
        + "\n".join(rows)
        + "\n"
    )


# ---------------------------------------------------------------------------
# Everything
# ---------------------------------------------------------------------------


def render_cli_reference(
    app: typer.Typer | None = None, exit_codes_source: str | None = None
) -> dict[str, str]:
    """Render every page of the CLI reference.

    :param app: The Typer app; defaults to :data:`apiome_cli.main.app`.
    :param exit_codes_source: Exit-codes module source (for tests).
    :returns: File name (inside :data:`CLI_REFERENCE_DIR`) → content.
    """
    root = root_command(app)
    root_ctx = click.Context(root, info_name=PROGRAM)
    commands = top_level(root)
    pages: dict[str, str] = {
        "_category_.json": json.dumps(
            {"label": "CLI", "position": 5, "collapsible": True, "collapsed": True},
            indent=2,
        )
        + "\n",
        "index.mdx": render_index(root, root_ctx, commands),
    }
    for position, (name, command) in enumerate(commands, start=2):
        pages[f"{name}.md"] = render_command_page(name, command, root_ctx, position)
    pages["exit-codes.md"] = render_exit_codes_page(
        exit_codes_source, position=len(commands) + 2
    )
    return pages
