"""Check an emitted RELAX NG grammar with jing — MFX-22.3 (#4134).

The XSD emitter's RELAX NG modes (:mod:`app.xml_schema_modes`) write a grammar in the XML syntax
(``.rng``) or the compact syntax (``.rnc``). The export validator (:mod:`app.export_validation`) runs
this after such an export: the grammar is written into a private scratch directory and ``jing`` checks
it — ``jing <file>`` for the XML syntax, ``jing -c <file>`` for the compact one. Given a schema and no
instance, jing checks only the schema: that it parses, every ``ref`` has a ``define``, the datatype
library knows each type and parameter, and the RELAX NG restrictions hold. That is what "validates
with jing" means here.

``jing`` is an optional bundled tool (:mod:`app.toolchain_packaging`, a JVM jar behind a ``bin/``
wrapper); without it, the grammar is still re-parsed by Apiome's RELAX NG reader, so the export is not
failed for the tool's absence.
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

__all__ = ["JING_TOOL_KEY", "RelaxNgCheckError", "check_relaxng_with_jing", "jing_available"]

#: Registry key of the bundled jing.
JING_TOOL_KEY = "jing"

#: ``<file>:<line>:<column>: error: <message>`` — the shape of a jing diagnostic.
_DIAGNOSTIC = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+):(?P<column>\d+): (?:fatal )?error: (?P<message>.+)$")


class RelaxNgCheckError(Exception):
    """jing could not run, or it rejected the grammar.

    Attributes:
        diagnostics: jing's error lines (``Shop.rng:12:5: error: …``), when it ran.
        unavailable: ``True`` when jing is not installed here (nothing was checked).
    """

    def __init__(self, message: str, *, diagnostics: Optional[List[str]] = None, unavailable: bool = False) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or []
        self.unavailable = unavailable


def jing_available() -> bool:
    """Whether ``jing`` can be resolved in this runtime (a cheap ``PATH`` / override lookup)."""
    from .toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    availability = probe_tool(JING_TOOL_KEY)
    return bool(availability and availability.available)


def _spec(compact: bool) -> ToolSpec:
    """The ``jing [-c]`` spec, derived from the bundled tool (keeps ``APIOME_JING_BIN``)."""
    tool = bundled_tool(JING_TOOL_KEY)
    return ToolSpec(
        key=JING_TOOL_KEY,
        executable=tool.executable if tool is not None else "jing",
        description="jing [-c] <grammar> → RELAX NG schema check (MFX-22.3).",
        base_args=("-c",) if compact else (),
        default_timeout_seconds=tool.default_timeout_seconds if tool is not None else 60.0,
        env_override_keys=(tool.env_override_key,) if tool is not None else (),
        parses_json=False,
    )


def _safe_name(path: str) -> str:
    """The file's base name, refusing anything that could escape the scratch directory."""
    name = posixpath.basename(path.replace("\\", "/"))
    if not name or name in (".", "..") or not name.endswith((".rng", ".rnc")):
        raise RelaxNgCheckError(f"Unsafe or non-RELAX NG grammar path: {path!r}")
    return name


def jing_diagnostics(output: str) -> List[str]:
    """The error lines of jing's output, each ``<file>:<line>:<column>: <message>`` with the folder removed.

    Args:
        output: jing's stdout and stderr, joined.

    Returns:
        One line per error, in the order jing printed them.
    """
    found: List[str] = []
    for line in output.splitlines():
        match = _DIAGNOSTIC.match(line.strip())
        if match:
            name = posixpath.basename(match.group("file").replace("\\", "/"))
            found.append(f"{name}:{match.group('line')}:{match.group('column')}: {match.group('message')}")
    return found


async def check_relaxng_with_jing(
    path: str,
    content: str,
    *,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
    policy: Optional[SandboxPolicy] = None,
) -> None:
    """Check one RELAX NG grammar with jing; return normally when jing accepts it.

    Args:
        path: The file's name (``Shop.rng`` or ``Shop.rnc``; the suffix picks the syntax).
        content: The grammar text.
        runner: The toolchain runner; defaults to :data:`app.toolchain_runner.default_runner`.
        timeout: Optional per-call timeout in seconds.
        policy: Optional sandbox policy override.

    Raises:
        RelaxNgCheckError: When the path is unsafe, jing is unavailable (``unavailable=True``), or jing
            rejects the grammar (``diagnostics`` holds its error lines).
    """
    name = _safe_name(path)
    active_runner = runner if runner is not None else default_runner
    with tempfile.TemporaryDirectory(prefix="apiome-jing-") as scratch:
        with open(os.path.join(scratch, name), "w", encoding="utf-8") as handle:
            handle.write(content)
        try:
            await active_runner.run_spec(
                _spec(name.endswith(".rnc")), [name], timeout=timeout, cwd=scratch, policy=policy
            )
        except ToolNotAvailableError as exc:
            raise RelaxNgCheckError(
                "The 'jing' tool is not available in this runtime; the grammar was not checked by jing.",
                unavailable=True,
            ) from exc
        except ToolExecutionError as exc:
            diagnostics = jing_diagnostics((exc.stdout or "") + "\n" + (exc.stderr or ""))
            raise RelaxNgCheckError(
                "jing rejected the grammar: " + ("; ".join(diagnostics[:5]) or str(exc)),
                diagnostics=diagnostics,
            ) from exc
        except ToolchainError as exc:
            raise RelaxNgCheckError(f"jing could not check the grammar: {exc}") from exc
