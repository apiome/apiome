"""Compile an emitted ``.fbs`` schema with the FlatBuffers compiler — MFX-30.1 (#4178).

The export validator (:mod:`app.export_validation`) runs this after a FlatBuffers export: the emitted
file is written into a private scratch directory and ``flatc --binary --schema`` compiles it, through
the toolchain runner (sandboxed, time-bounded, MFI-5.1/5.3). That builds the schema's binary reflection
(``.bfbs``), which no language generator is needed for, after ``flatc`` has parsed and checked the whole
schema (names, types, field ids, enum values and defaults, union members, ``root_type``) — which is
what "compiles" means here. The ``.bfbs`` itself is discarded.

``flatc`` is an optional bundled tool (:mod:`app.toolchain_packaging`); without it, callers fall back to
re-parsing with the FlatBuffers reader rather than failing the export.
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

__all__ = ["FLATC_TOOL_KEY", "FlatcCompileError", "compile_fbs_schema", "flatc_available"]

#: Registry key of the bundled FlatBuffers compiler.
FLATC_TOOL_KEY = "flatc"


class FlatcCompileError(Exception):
    """``flatc`` could not run, or it rejected the schema.

    Attributes:
        diagnostics: The compiler's error lines (``error: file.fbs:3: 10: …``), when it ran.
        unavailable: ``True`` when the compiler is not installed here (nothing was checked).
    """

    def __init__(
        self, message: str, *, diagnostics: Optional[List[str]] = None, unavailable: bool = False
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []
        self.unavailable = unavailable


def flatc_available() -> bool:
    """Whether the ``flatc`` compiler can be resolved in this runtime (a cheap ``PATH`` lookup)."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    availability = probe_tool(FLATC_TOOL_KEY)
    return bool(availability and availability.available)


def _compile_spec() -> ToolSpec:
    """The ``flatc --binary --schema -o .`` spec, derived from the bundled tool (keeps ``APIOME_FLATC_BIN``)."""
    tool = bundled_tool(FLATC_TOOL_KEY)
    return ToolSpec(
        key=FLATC_TOOL_KEY,
        executable=tool.executable if tool is not None else "flatc",
        description="flatc --binary --schema → schema check (MFX-30.1).",
        base_args=("--binary", "--schema", "-o", "."),
        default_timeout_seconds=tool.default_timeout_seconds if tool is not None else 60.0,
        env_override_keys=(tool.env_override_key,) if tool is not None else (),
        parses_json=False,
    )


def _safe_name(path: str) -> str:
    """The file's base name, refusing anything that could escape the scratch directory."""
    name = posixpath.basename(path.replace("\\", "/"))
    if not name or name in (".", "..") or not name.endswith(".fbs"):
        raise FlatcCompileError(f"Unsafe or non-.fbs schema path: {path!r}")
    return name


async def compile_fbs_schema(
    path: str,
    content: str,
    *,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
    policy: Optional[SandboxPolicy] = None,
) -> None:
    """Compile one ``.fbs`` file with ``flatc``; return normally when it compiles.

    Args:
        path: The file's name (``Shop.fbs``).
        content: The schema text.
        runner: The toolchain runner; defaults to :data:`app.toolchain_runner.default_runner`.
        timeout: Optional per-call timeout in seconds.
        policy: Optional sandbox policy override.

    Raises:
        FlatcCompileError: When the path is unsafe, ``flatc`` is unavailable (``unavailable=True``),
            or the compiler rejects the schema (``diagnostics`` holds its error lines).
    """
    name = _safe_name(path)
    active_runner = runner if runner is not None else default_runner
    with tempfile.TemporaryDirectory(prefix="apiome-flatc-") as scratch:
        with open(os.path.join(scratch, name), "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            await active_runner.run_spec(_compile_spec(), [name], timeout=timeout, cwd=scratch, policy=policy)
        except ToolNotAvailableError as exc:
            raise FlatcCompileError(
                "The 'flatc' tool is not available in this runtime; the schema was not compiled.",
                unavailable=True,
            ) from exc
        except ToolExecutionError as exc:
            lines = (exc.stderr or "").splitlines() + (exc.stdout or "").splitlines()
            diagnostics = [line.strip() for line in lines if "error" in line.lower()]
            raise FlatcCompileError(
                "flatc rejected the schema: " + ("; ".join(diagnostics[:5]) or str(exc)),
                diagnostics=diagnostics,
            ) from exc
        except ToolchainError as exc:
            raise FlatcCompileError(f"flatc could not compile the schema: {exc}") from exc
