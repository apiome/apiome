"""Tests for interactive and batch CLI execution via run.sh helper."""

from __future__ import annotations

import io
import sys
from unittest.mock import patch

import pytest

from apiome_cli.run_interactive import _run_command_line, main


def test_run_command_line_skips_blank_and_comments() -> None:
    """Blank lines and comments do not invoke the CLI."""
    with patch("apiome_cli.run_interactive.run") as mock_run:
        assert _run_command_line("") is True
        assert _run_command_line("   ") is True
        assert _run_command_line("# doctor") is True
        mock_run.assert_not_called()


def test_run_command_line_help_shows_concise_usage(capsys: pytest.CaptureFixture[str]) -> None:
    """help in interactive mode prints concise usage without invoking run()."""
    with patch("apiome_cli.run_interactive.run") as mock_run:
        assert _run_command_line("help") is True
        mock_run.assert_not_called()
    captured = capsys.readouterr()
    assert "apiome — Command-line client" in captured.out


def test_run_command_line_help_subcommand_invokes_show_cli_help() -> None:
    """help <subcommand> forwards to subcommand help via show_cli_help."""
    with patch("apiome_cli.run_interactive.show_cli_help") as mock_help:
        mock_help.return_value = 0
        assert _run_command_line("help doctor") is True
        mock_help.assert_called_once_with(["doctor"])


def test_run_command_line_stop_words_end_session() -> None:
    """exit and quit end the interactive session without running the CLI."""
    with patch("apiome_cli.run_interactive.run") as mock_run:
        assert _run_command_line("exit") is False
        assert _run_command_line("quit") is False
        mock_run.assert_not_called()


def test_run_command_line_invokes_run_with_parsed_argv() -> None:
    """A command line is split with shlex and passed to run()."""
    with patch("apiome_cli.run_interactive.run") as mock_run:
        assert _run_command_line("doctor") is True
        mock_run.assert_called_once()
        assert sys.argv == ["apiome", "doctor"]


def test_run_command_line_preserves_quoted_arguments() -> None:
    """Quoted tokens survive shlex splitting."""
    with patch("apiome_cli.run_interactive.run") as mock_run:
        assert _run_command_line('config set base-url "http://127.0.0.1:8000"') is True
        mock_run.assert_called_once()
        assert sys.argv == [
            "apiome",
            "config",
            "set",
            "base-url",
            "http://127.0.0.1:8000",
        ]


def test_run_command_line_reports_nonzero_exit() -> None:
    """SystemExit from run() is reported on stderr without stopping the REPL."""
    with patch("apiome_cli.run_interactive.run", side_effect=SystemExit(2)):
        assert _run_command_line("projects list") is True


def test_main_runs_batch_lines_from_stdin() -> None:
    """Batch mode executes each stdin line in order."""
    stdin = io.StringIO("doctor\nprojects list\n")
    with (
        patch("apiome_cli.run_interactive.run") as mock_run,
        patch.object(sys, "stdin", stdin),
    ):
        stdin.isatty = lambda: False  # type: ignore[method-assign]
        main()
    assert mock_run.call_count == 2


def test_main_interactive_stops_on_exit(capsys: pytest.CaptureFixture[str]) -> None:
    """Interactive mode stops when the user types exit."""
    inputs = iter(["doctor", "exit", "health"])
    stdin = io.StringIO()
    stdin.isatty = lambda: True  # type: ignore[method-assign]

    with (
        patch("apiome_cli.run_interactive.run"),
        patch("builtins.input", side_effect=lambda _prompt: next(inputs)),
        patch.object(sys, "stdin", stdin),
    ):
        main()

    captured = capsys.readouterr()
    assert "Interactive apiome CLI" in captured.err
