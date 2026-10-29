"""Compile an emitted ``.thrift`` IDL with the Apache Thrift compiler — MFX-25.1 (#4151).

The export validator (:mod:`app.export_validation`) runs this after a Thrift export: the emitted
file is written into a private scratch directory and ``thrift --gen json`` compiles it, through the
toolchain runner (sandboxed, time-bounded, MFI-5.1/5.3). The generated JSON is discarded — only the
verdict and the diagnostics matter. ``json`` is the cheapest generator, and every generator parses
and type-checks the whole IDL first (identifiers, reserved words, undefined types, ``throws``
holding only exceptions, field ids), which is what "compiles" means here.

``thrift`` is an optional bundled tool (:mod:`app.toolchain_packaging`); without it, callers fall
back to re-parsing with the Thrift reader rather than failing the export.
"""

from __future__ import annotations

import os
import posixpath
import tempfile
from typing import List, Optional

from .toolchain_packaging import bundled_tool
from .toolchain_runner import (
    ToolchainError,
    ToolchainRunner,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolSpec,
    default_runner,
)
from .toolchain_sandbox import SandboxPolicy

__all__ = ["THRIFT_TOOL_KEY", "ThriftCompileError", "compile_thrift_idl", "thrift_available"]

#: Registry key of the bundled Thrift compiler.
THRIFT_TOOL_KEY = "thrift"


class ThriftCompileError(Exception):
    """``thrift`` could not run, or it rejected the IDL.

    Attributes:
        diagnostics: The compiler's error lines (``[ERROR:file:line] …``), when it ran.
        unavailable: ``True`` when the compiler is not installed here (nothing was checked).
    """

    def __init__(
        self, message: str, *, diagnostics: Optional[List[str]] = None, unavailable: bool = False
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []
        self.unavailable = unavailable


def thrift_available() -> bool:
    """Whether the ``thrift`` compiler can be resolved in this runtime (a cheap ``PATH`` lookup)."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    availability = probe_tool(THRIFT_TOOL_KEY)
    return bool(availability and availability.available)


def _compile_spec() -> ToolSpec:
    """The ``thrift -o . --gen json`` spec, derived from the bundled tool (keeps ``APIOME_THRIFT_BIN``)."""
    tool = bundled_tool(THRIFT_TOOL_KEY)
    return ToolSpec(
        key=THRIFT_TOOL_KEY,
        executable=tool.executable if tool is not None else "thrift",
        description="thrift --gen json → IDL check (MFX-25.1).",
        base_args=("-o", ".", "--gen", "json"),
        default_timeout_seconds=tool.default_timeout_seconds if tool is not None else 60.0,
        env_override_keys=(tool.env_override_key,) if tool is not None else (),
        parses_json=False,
    )


def _safe_name(path: str) -> str:
    """The file's base name, refusing anything that could escape the scratch directory."""
    name = posixpath.basename(path.replace("\\", "/"))
    if not name or name in (".", "..") or not name.endswith(".thrift"):
        raise ThriftCompileError(f"Unsafe or non-.thrift IDL path: {path!r}")
    return name


async def compile_thrift_idl(
    path: str,
    content: str,
    *,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
    policy: Optional[SandboxPolicy] = None,
) -> None:
    """Compile one ``.thrift`` file with ``thrift``; return normally when it compiles.

    Args:
        path: The file's name (``Shop.thrift``).
        content: The IDL text.
        runner: The toolchain runner; defaults to :data:`app.toolchain_runner.default_runner`.
        timeout: Optional per-call timeout in seconds.
        policy: Optional sandbox policy override.

    Raises:
        ThriftCompileError: When the path is unsafe, ``thrift`` is unavailable (``unavailable=True``),
            or the compiler rejects the IDL (``diagnostics`` holds its error lines).
    """
    name = _safe_name(path)
    active_runner = runner if runner is not None else default_runner
    with tempfile.TemporaryDirectory(prefix="apiome-thrift-") as scratch:
        with open(os.path.join(scratch, name), "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            await active_runner.run_spec(_compile_spec(), [name], timeout=timeout, cwd=scratch, policy=policy)
        except ToolNotAvailableError as exc:
            raise ThriftCompileError(
                "The 'thrift' tool is not available in this runtime; the IDL was not compiled.",
                unavailable=True,
            ) from exc
        except ToolExecutionError as exc:
            lines = (exc.stderr or "").splitlines() + (exc.stdout or "").splitlines()
            diagnostics = [line.strip() for line in lines if "ERROR" in line or "error" in line.lower()]
            raise ThriftCompileError(
                "thrift rejected the IDL: " + ("; ".join(diagnostics[:5]) or str(exc)),
                diagnostics=diagnostics,
            ) from exc
        except ToolchainError as exc:
            raise ThriftCompileError(f"thrift could not compile the IDL: {exc}") from exc
