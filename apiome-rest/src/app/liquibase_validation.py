"""Validate an emitted Liquibase changelog with ``liquibase validate`` — MFX-35.3 (#4313).

The SQL DDL export's ``liquibase`` output (:mod:`app.sql_changelog`) is a *formatted SQL* changelog.
Liquibase reads it — the ``--liquibase formatted sql`` header, each ``--changeset author:id`` and its
attributes — with its own parser, so the check that matters is Liquibase's: the toolchain tool
``liquibase`` (:data:`LIQUIBASE_TOOL_KEY`, the pinned Liquibase CLI behind a wrapper, see
:mod:`app.toolchain_packaging`) runs ``validate`` against an **offline** database
(``--url=offline:<database>``), so no server is needed and nothing is applied.

:func:`validate_liquibase_changelog` writes the changelog to a private temporary directory, runs the
tool there (sandboxed, no network, analytics and banner off) and returns its problems: an empty list
when Liquibase accepts the changelog, one problem per error line it prints otherwise. It raises
:class:`LiquibaseUnavailableError` when the tool is not installed in this runtime, so the export gate can
report the check as skipped rather than passed.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import List

from .toolchain_runner import ToolchainError, ToolExecutionError, ToolNotAvailableError, run_tool_blocking

__all__ = [
    "LIQUIBASE_TOOL_KEY",
    "LiquibaseUnavailableError",
    "liquibase_available",
    "offline_url",
    "validate_liquibase_changelog",
]

LIQUIBASE_TOOL_KEY = "liquibase"
_TIMEOUT_SECONDS = 180.0
#: Export dialect → the database an offline URL names. Standard SQL has no Liquibase database of its own;
#: ``validate`` checks the changelog, not the statements, so PostgreSQL's stands in.
_OFFLINE_DATABASES = {"postgres": "postgresql", "mysql": "mysql", "ansi": "postgresql"}
#: Lines of Liquibase's output that carry no problem (its progress and summary chatter).
_NOISE = ("Starting Liquibase", "Liquibase Version", "Liquibase Open Source", "Liquibase Community",
          "Running Changeset", "Liquibase command", "No validation errors", "####", "##  ")


class LiquibaseUnavailableError(Exception):
    """The ``liquibase`` tool is not installed in this runtime."""


def liquibase_available() -> bool:
    """Whether the ``liquibase`` tool resolves in this runtime (a cheap lookup, no subprocess)."""
    from .toolchain_packaging import bundled_tool, probe_tool  # noqa: PLC0415

    tool = bundled_tool(LIQUIBASE_TOOL_KEY)
    if tool is None:
        return False
    status = probe_tool(LIQUIBASE_TOOL_KEY)
    return bool(status and status.available)


def offline_url(dialect: str) -> str:
    """The offline database URL ``validate`` runs against for an export dialect (``offline:postgresql``)."""
    return f"offline:{_OFFLINE_DATABASES.get(dialect, 'postgresql')}"


def _problems(text: str) -> List[str]:
    """The error lines of Liquibase's output (its message when no line stands out)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    errors = [line for line in lines if not line.startswith(_NOISE)]
    flagged = [line for line in errors if "error" in line.lower() or "fail" in line.lower()
               or "invalid" in line.lower() or "unexpected" in line.lower()]
    return flagged or errors[-5:] or ["liquibase validate failed without a message"]


def validate_liquibase_changelog(text: str, *, dialect: str, name: str = "changelog.sql") -> List[str]:
    """Run ``liquibase validate`` over one formatted-SQL changelog.

    Args:
        text: The changelog.
        dialect: The export dialect (``postgres``, ``mysql``, ``ansi``), naming the offline database.
        name: The file name Liquibase records the changesets under.

    Returns:
        Liquibase's problems; empty when the changelog validates.

    Raises:
        LiquibaseUnavailableError: The tool is not installed in this runtime.
    """
    work = Path(tempfile.mkdtemp(prefix="apiome-liquibase-"))
    try:
        changelog = work / (Path(name).name or "changelog.sql")
        changelog.write_text(text, encoding="utf-8")
        args = [f"--changelog-file={changelog.name}", f"--url={offline_url(dialect)}",
                f"--search-path={work}", "validate"]
        env = {"HOME": str(work), "LIQUIBASE_ANALYTICS_ENABLED": "false", "LIQUIBASE_SHOW_BANNER": "false"}
        try:
            run_tool_blocking(LIQUIBASE_TOOL_KEY, args, timeout=_TIMEOUT_SECONDS, thread_name="liquibase",
                              cwd=str(work), extra_env=env)
        except ToolNotAvailableError as exc:
            raise LiquibaseUnavailableError("liquibase is not installed on this server.") from exc
        except ToolExecutionError as exc:
            return _problems(f"{exc.stdout or ''}\n{exc.stderr or ''}" or str(exc))
        except ToolchainError as exc:
            return [f"liquibase validate failed: {exc}"]
        return []
    finally:
        shutil.rmtree(work, ignore_errors=True)
