"""Check an emitted OMG IDL file with an IDL compiler — MFX-28.3 (#4170).

The OMG IDL emitter (:class:`app.corbaidl_emitter.CorbaIdlEmitter`, MFX-28.1) writes one ``.idl`` file in
one of two profiles, and each profile has its own reference compiler:

* **CORBA** → ``omniidl`` (omniORB). Run with no back-end, it parses and checks the IDL and writes
  nothing. It handles interfaces and exceptions, and rejects every ``@annotation``.
* **DDS** → ``idlc`` (Eclipse Cyclone DDS). It handles ``@key`` / ``@optional``, rejects interfaces,
  exceptions and wide characters, and writes generated ``.c`` / ``.h`` files, which land in the scratch
  directory and are discarded.

:func:`idl_compiler_for` picks the compiler from what the file says: the emitter's header names the
profile (``// Generated OMG IDL 4.2 (DDS profile)``), and when comments are switched off an annotation
line means the DDS profile.

The file is written into a private scratch directory and the compiler runs there through the toolchain
runner (sandboxed, time-bounded, MFI-5.1/5.3; the timeout also bounds ``idlc``, which does not finish on a
recursive type). Both compilers are optional bundled tools (:mod:`app.toolchain_packaging`); without one,
callers fall back to re-parsing with Apiome's OMG IDL reader rather than failing the export.
"""

from __future__ import annotations

import os
import posixpath
import re
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

__all__ = [
    "IDLC_TOOL_KEY",
    "OMNIIDL_TOOL_KEY",
    "OmgIdlCompileError",
    "compile_omg_idl",
    "idl_compiler_available",
    "idl_compiler_for",
]

#: Registry key of the CORBA-profile compiler (omniORB's ``omniidl``).
OMNIIDL_TOOL_KEY = "omniidl"
#: Registry key of the DDS-profile compiler (Eclipse Cyclone DDS ``idlc``).
IDLC_TOOL_KEY = "idlc"

_DDS_HEADER_RE = re.compile(r"^//\s*Generated OMG IDL[^\n]*\(DDS profile\)", re.MULTILINE)
_CORBA_HEADER_RE = re.compile(r"^//\s*Generated OMG IDL[^\n]*\(CORBA profile\)", re.MULTILINE)
#: An annotation (``@key``, ``@optional``, ``@topic``): OMG IDL uses ``@`` for nothing else.
_ANNOTATION_RE = re.compile(r"(?<![\w\"'])@[A-Za-z_]")
_DIAGNOSTIC_RE = re.compile(r"\berror\b", re.IGNORECASE)
#: The compiler's closing tally (``omniidl: 1 error.``), which repeats nothing a finding needs.
_SUMMARY_RE = re.compile(r"^\S+:\s*\d+\s+errors?\.?$", re.IGNORECASE)


class OmgIdlCompileError(Exception):
    """The IDL compiler could not run, or it rejected the IDL.

    Attributes:
        compiler: The tool key that ran (``omniidl`` / ``idlc``).
        diagnostics: The compiler's error lines (``Shop.idl:3: Error in look-up of 'Missing'…``).
        unavailable: ``True`` when the compiler is not installed here (nothing was checked).
    """

    def __init__(
        self, message: str, *, compiler: str, diagnostics: Optional[List[str]] = None, unavailable: bool = False
    ) -> None:
        super().__init__(message)
        self.compiler = compiler
        self.diagnostics = diagnostics or []
        self.unavailable = unavailable


def idl_compiler_for(text: str) -> str:
    """The compiler that checks ``text``: ``idlc`` for the DDS profile, ``omniidl`` for CORBA.

    Args:
        text: The emitted IDL.

    Returns:
        :data:`IDLC_TOOL_KEY` when the header names the DDS profile, or (without a header) when the file
        has an annotation line; :data:`OMNIIDL_TOOL_KEY` otherwise — a DDS-profile file with neither is
        plain IDL that both compilers accept.
    """
    if _DDS_HEADER_RE.search(text):
        return IDLC_TOOL_KEY
    if _CORBA_HEADER_RE.search(text):
        return OMNIIDL_TOOL_KEY
    return IDLC_TOOL_KEY if _ANNOTATION_RE.search(text) else OMNIIDL_TOOL_KEY


def idl_compiler_available(key: str) -> bool:
    """Whether the compiler ``key`` can be resolved in this runtime (a cheap ``PATH`` lookup)."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    availability = probe_tool(key)
    return bool(availability and availability.available)


def _compile_spec(key: str) -> ToolSpec:
    """The compiler's spec, derived from the bundled tool (keeps its ``APIOME_*_BIN`` override)."""
    tool = bundled_tool(key)
    return ToolSpec(
        key=key,
        executable=tool.executable if tool is not None else key,
        description=f"{key} → OMG IDL check (MFX-28.3).",
        default_timeout_seconds=tool.default_timeout_seconds if tool is not None else 60.0,
        env_override_keys=(tool.env_override_key,) if tool is not None else (),
        parses_json=False,
    )


def _safe_name(path: str, key: str) -> str:
    """The file's base name, refusing anything that could escape the scratch directory."""
    name = posixpath.basename(path.replace("\\", "/"))
    if not name or name in (".", "..") or not name.endswith(".idl") or name.startswith("-"):
        raise OmgIdlCompileError(f"Unsafe or non-.idl path: {path!r}", compiler=key)
    return name


async def compile_omg_idl(
    path: str,
    content: str,
    *,
    compiler: Optional[str] = None,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
    policy: Optional[SandboxPolicy] = None,
) -> str:
    """Check one ``.idl`` file with its profile's compiler; return the compiler's key when it passes.

    Args:
        path: The file's name (``Shop.idl``).
        content: The IDL text.
        compiler: Force a compiler key; defaults to :func:`idl_compiler_for`.
        runner: The toolchain runner; defaults to :data:`app.toolchain_runner.default_runner`.
        timeout: Optional per-call timeout in seconds.
        policy: Optional sandbox policy override.

    Returns:
        The key of the compiler that accepted the file.

    Raises:
        OmgIdlCompileError: When the path is unsafe, the compiler is unavailable (``unavailable=True``),
            or it rejects the IDL (``diagnostics`` holds its error lines).
    """
    key = compiler or idl_compiler_for(content)
    name = _safe_name(path, key)
    active_runner = runner if runner is not None else default_runner
    with tempfile.TemporaryDirectory(prefix="apiome-idl-") as scratch:
        with open(os.path.join(scratch, name), "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            await active_runner.run_spec(_compile_spec(key), [name], timeout=timeout, cwd=scratch, policy=policy)
        except ToolNotAvailableError as exc:
            raise OmgIdlCompileError(
                f"The {key!r} compiler is not available in this runtime; the IDL was not compiled.",
                compiler=key,
                unavailable=True,
            ) from exc
        except ToolExecutionError as exc:
            lines = (exc.stderr or "").splitlines() + (exc.stdout or "").splitlines()
            diagnostics = [line.strip() for line in lines
                           if _DIAGNOSTIC_RE.search(line) and not _SUMMARY_RE.match(line.strip())]
            if not diagnostics:
                diagnostics = [line.strip() for line in lines if line.strip()][:5]
            raise OmgIdlCompileError(
                f"{key} rejected the IDL: " + ("; ".join(diagnostics[:5]) or str(exc)),
                compiler=key,
                diagnostics=diagnostics,
            ) from exc
        except ToolchainError as exc:
            raise OmgIdlCompileError(f"{key} could not check the IDL: {exc}", compiler=key) from exc
    return key
