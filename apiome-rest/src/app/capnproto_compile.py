"""Compile an emitted ``.capnp`` schema with the Cap'n Proto compiler — MFX-30.2 (#4179).

The export validator (:mod:`app.export_validation`) runs this after a Cap'n Proto export: the emitted
files are written into a private scratch directory and ``capnp compile`` checks them, through the
toolchain runner (sandboxed, time-bounded, MFI-5.1/5.3). The compiled code-generator request it
writes to stdout is discarded — only the verdict and the diagnostics matter.

``capnp`` is an optional bundled tool (:mod:`app.toolchain_packaging`); without it, callers report
the artifact as not re-validated rather than failing it.
"""

from __future__ import annotations

import os
import posixpath
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Sequence

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

__all__ = ["CAPNP_TOOL_KEY", "CapnpCompileError", "CapnpFile", "compile_capnp_schema"]

#: Registry key of the bundled Cap'n Proto compiler.
CAPNP_TOOL_KEY = "capnp"
_MAX_FILES = 64


@dataclass(frozen=True)
class CapnpFile:
    """One schema file to compile: its name (as other files import it) and its text."""

    path: str
    content: str


class CapnpCompileError(Exception):
    """``capnp`` could not run, or it rejected the schema.

    Attributes:
        diagnostics: The compiler's error lines (``file:line:col: error: …``), when it ran.
        unavailable: ``True`` when the compiler is not installed here (nothing was checked).
    """

    def __init__(
        self, message: str, *, diagnostics: Optional[List[str]] = None, unavailable: bool = False
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []
        self.unavailable = unavailable


def _compile_spec() -> ToolSpec:
    """The ``capnp compile -o-`` spec, derived from the bundled tool (keeps ``APIOME_CAPNP_BIN``)."""
    tool = bundled_tool(CAPNP_TOOL_KEY)
    return ToolSpec(
        key=CAPNP_TOOL_KEY,
        executable=tool.executable if tool is not None else "capnp",
        description="capnp compile → schema check (MFX-30.2).",
        base_args=("compile", "-o-"),
        default_timeout_seconds=tool.default_timeout_seconds if tool is not None else 60.0,
        env_override_keys=(tool.env_override_key,) if tool is not None else (),
        parses_json=False,
    )


def _safe_name(path: str) -> str:
    """The file's base name, refusing anything that could escape the scratch directory."""
    name = posixpath.basename(path.replace("\\", "/"))
    if not name or name in (".", "..") or not name.endswith(".capnp"):
        raise CapnpCompileError(f"Unsafe or non-.capnp schema path: {path!r}")
    return name


async def compile_capnp_schema(
    files: Sequence[CapnpFile],
    *,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
    policy: Optional[SandboxPolicy] = None,
) -> None:
    """Compile ``files`` with ``capnp``; return normally when every file compiles.

    Args:
        files: The schema files. They are written side by side, so one may import another by name.
        runner: The toolchain runner; defaults to :data:`app.toolchain_runner.default_runner`.
        timeout: Optional per-call timeout in seconds.
        policy: Optional sandbox policy override.

    Raises:
        CapnpCompileError: When there are no (or too many) files, a path is unsafe, ``capnp`` is
            unavailable (``unavailable=True``), or the compiler rejects the schema
            (``diagnostics`` holds its error lines).
    """
    if not files:
        raise CapnpCompileError("At least one .capnp file is required")
    if len(files) > _MAX_FILES:
        raise CapnpCompileError(f"Too many .capnp files ({len(files)}); the limit is {_MAX_FILES}")
    names = [_safe_name(f.path) for f in files]
    active_runner = runner if runner is not None else default_runner

    with tempfile.TemporaryDirectory(prefix="apiome-capnp-") as scratch:
        for name, file in zip(names, files):
            with open(os.path.join(scratch, name), "w", encoding="utf-8") as handle:
                handle.write(file.content)
        try:
            await active_runner.run_spec(
                _compile_spec(), names, timeout=timeout, cwd=scratch, policy=policy
            )
        except ToolNotAvailableError as exc:
            raise CapnpCompileError(
                "The 'capnp' tool is not available in this runtime; the schema was not compiled.",
                unavailable=True,
            ) from exc
        except ToolExecutionError as exc:
            diagnostics = [line for line in exc.stderr.splitlines() if line.strip()]
            raise CapnpCompileError(
                "capnp rejected the schema: " + ("; ".join(diagnostics[:5]) or str(exc)),
                diagnostics=diagnostics,
            ) from exc
        except ToolchainError as exc:
            raise CapnpCompileError(f"capnp could not compile the schema: {exc}") from exc
