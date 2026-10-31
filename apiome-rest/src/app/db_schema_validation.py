"""DBML and Prisma schema validation through the bundled Node toolchain — MFX-35.2 (#4312).

The SQL DDL export (:mod:`app.sql_ddl_emitter`) can write its relational projection as DBML or as a
``schema.prisma``. Neither language has a Python reader, so each output is checked by its own
reference tool, run through :mod:`app.toolchain_runner` (sandboxed, no network):

* **DBML** — ``@dbml/core``'s ``dbmlv2`` parser (the one dbdiagram.io uses), tool ``dbml-validator``
  (``toolchain/dbml-validate.mjs``);
* **Prisma** — ``prisma validate`` from the pinned Prisma CLI, tool ``prisma-validator``
  (``toolchain/prisma-validate.mjs``).

Both are hard dependencies (:data:`app.toolchain_selfcheck.REQUIRED_TOOL_KEYS`): an enforcing
deployment refuses to start without them. Each function returns the tool's diagnostics — an empty
list when the document is valid — and raises :class:`~app.toolchain_runner.ToolNotAvailableError`
when the tool is not installed in this runtime, so the caller decides how to report that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .toolchain_runner import ToolOutputError, default_runner

__all__ = [
    "DBML_VALIDATOR_TOOL_KEY",
    "PRISMA_VALIDATOR_TOOL_KEY",
    "SchemaDiagnostic",
    "db_schema_validator_available",
    "validate_dbml",
    "validate_prisma",
]

#: Registry keys of the two bundled wrappers (declared in :mod:`app.toolchain_packaging`).
DBML_VALIDATOR_TOOL_KEY = "dbml-validator"
PRISMA_VALIDATOR_TOOL_KEY = "prisma-validator"


@dataclass(frozen=True)
class SchemaDiagnostic:
    """One problem a validator found.

    Attributes:
        message: The tool's own message.
        line: The 1-based line it points at, when the tool names one.
        column: The 1-based column (DBML only), when the tool names one.
    """

    message: str
    line: Optional[int] = None
    column: Optional[int] = None

    def __str__(self) -> str:
        where = f"line {self.line}" + (f", column {self.column}" if self.column else "") if self.line else ""
        return f"{where}: {self.message}" if where else self.message


def db_schema_validator_available(tool_key: str) -> bool:
    """Whether the validator ``tool_key`` resolves in this runtime (a cheap lookup, no subprocess).

    Args:
        tool_key: :data:`DBML_VALIDATOR_TOOL_KEY` or :data:`PRISMA_VALIDATOR_TOOL_KEY`.

    Returns:
        ``True`` when the tool's executable (or its ``APIOME_*_BIN`` override) is on hand.
    """
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    availability = probe_tool(tool_key)
    return bool(availability and availability.available)


async def _run(tool_key: str, text: str, *, runner: Any = None) -> List[SchemaDiagnostic]:
    """Feed ``text`` to the wrapper ``tool_key`` and read its ``{ok, diagnostics}`` verdict.

    Raises:
        ToolNotAvailableError: The tool is not installed here.
        ToolchainError: The wrapper failed, timed out, or answered outside its contract.
    """
    from .toolchain_packaging import register_bundled_tools

    register_bundled_tools()
    result = await (runner or default_runner).run(tool_key, [], stdin=text)
    payload = result.parsed_json
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        raise ToolOutputError(tool_key, result.stdout[:500], "the output is not an {ok, diagnostics} verdict")
    if payload["ok"]:
        return []
    diagnostics = [
        SchemaDiagnostic(
            message=str(item.get("message") or "invalid"),
            line=item.get("line") if isinstance(item.get("line"), int) else None,
            column=item.get("column") if isinstance(item.get("column"), int) else None,
        )
        for item in payload.get("diagnostics") or []
        if isinstance(item, dict)
    ]
    return diagnostics or [SchemaDiagnostic(message=f"{tool_key} rejected the document")]


async def validate_dbml(text: str, *, runner: Any = None) -> List[SchemaDiagnostic]:
    """Parse ``text`` with ``@dbml/core`` (``dbmlv2``).

    Args:
        text: A DBML document.
        runner: Optional toolchain runner override (tests).

    Returns:
        The parse errors; empty when the document parses.

    Raises:
        ToolNotAvailableError: ``dbml-validator`` is not installed here.
        ToolchainError: The wrapper itself failed.
    """
    return await _run(DBML_VALIDATOR_TOOL_KEY, text, runner=runner)


async def validate_prisma(text: str, *, runner: Any = None) -> List[SchemaDiagnostic]:
    """Run ``prisma validate`` on ``text``.

    Args:
        text: A ``schema.prisma`` document.
        runner: Optional toolchain runner override (tests).

    Returns:
        The validation errors; empty when the schema is valid.

    Raises:
        ToolNotAvailableError: ``prisma-validator`` is not installed here.
        ToolchainError: The wrapper itself failed.
    """
    return await _run(PRISMA_VALIDATOR_TOOL_KEY, text, runner=runner)
