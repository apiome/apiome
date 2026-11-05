"""Toolchain check console — MFX-44.6 (#4372).

For an IDL target the authoritative *test* of an emitted artifact is the format's own toolchain:
``buf lint`` on a proto bundle, ``tsp compile`` on TypeSpec, ``smithy build``, ``capnp compile``…
Each emitter already **declares** the checks that apply to its output
(:func:`app.export_test_tools.toolchain_check`, MFX-44.1). This module is what makes a declared check
**runnable on demand**: it knows, per ``(tool, check)``, which emitted files the check reads and the
argv that runs it, stages the artifact in a scratch directory, and runs it through the shared
toolchain runner (:mod:`app.toolchain_runner`, MFI-5.1 / MFX-8.3 reuse) — sandboxed, timed out and
concurrency-capped exactly like every other tool call — while handing each output chunk to the caller
as it is produced, so the Studio's console can stream it.

Nothing here decides *whether* a target has a check: that stays registry data. A declared check with
no command here is refused rather than guessed at, and a check whose tool is not installed reports
**unavailable** with the reason instead of failing.

The REST binding is :mod:`app.export_tool_check_routes`.
"""

from __future__ import annotations

import codecs
import io
import posixpath
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .emitter import EmitResult
from .toolchain_runner import (
    ToolchainError,
    ToolchainRunner,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolOutputTooLargeError,
    ToolResourceLimitError,
    ToolSpec,
    ToolTimeoutError,
    default_runner,
)

__all__ = [
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_FILES",
    "ExportToolCheckResult",
    "ToolCheckArtifactError",
    "ToolCheckCommand",
    "ToolCheckStatus",
    "files_from_download_body",
    "files_from_emit",
    "output_event",
    "result_event",
    "run_tool_check",
    "start_event",
    "tool_check_command",
]

#: The most files an artifact may stage for one check (a proto bundle is tens, not thousands).
MAX_ARTIFACT_FILES = 500

#: The most bytes an artifact may stage for one check, summed over its files.
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024

#: What a staged artifact is: relative path → UTF-8 text.
ArtifactFiles = Dict[str, str]

#: Receives each console event (``start`` / ``output``) as a JSON-ready dict.
EventSink = Callable[[Dict[str, Any]], None]


class ToolCheckArtifactError(ValueError):
    """The artifact cannot be staged for a check (unsafe path, too large, not a bundle)."""


class ToolCheckStatus(str, Enum):
    """How a check run ended — what the console's status chip says."""

    PASSED = "passed"  # the tool exited 0
    FAILED = "failed"  # the tool exited non-zero: the artifact did not pass the check
    TIMED_OUT = "timed_out"  # the tool exceeded its timeout and was killed
    UNAVAILABLE = "unavailable"  # the tool is not installed on this server
    ERROR = "error"  # the check could not run (nothing to check, output cap, sandbox…)


@dataclass(frozen=True)
class ToolCheckCommand:
    """How to run one declared ``(tool, check)`` against an emitted artifact.

    Attributes:
        tool: The toolchain runner's tool key (``buf``).
        check: The check name the emitter declares (``lint``).
        extensions: File suffixes the check reads; the artifact must contain at least one.
        args: Builds the argv after the executable from the matching file paths (sorted).
        config_files: Files written beside the artifact when it does not carry its own (a minimal
            ``buf.yaml``), so the tool runs with its documented defaults.
        prepare: Optional hook run on the staged scratch directory before the tool (linking the
            TypeSpec libraries); returns extra environment variables for the run.
        binary_stdout: The tool writes binary data to stdout (``capnp compile -o-``); the console
            shows stderr only and notes how much stdout was discarded.
        exclude: Path suffixes never fed to the check even though they match ``extensions``.
    """

    tool: str
    check: str
    extensions: Tuple[str, ...]
    args: Callable[[List[str]], List[str]]
    config_files: Mapping[str, str] = field(default_factory=dict)
    prepare: Optional[Callable[[Path], Dict[str, str]]] = None
    binary_stdout: bool = False
    exclude: Tuple[str, ...] = ()

    def matching(self, paths: Sequence[str]) -> List[str]:
        """The artifact paths this check reads, sorted.

        Args:
            paths: Every staged path.

        Returns:
            The paths ending in one of :attr:`extensions` and none of :attr:`exclude`.
        """
        return sorted(
            p for p in paths
            if p.lower().endswith(self.extensions) and not p.lower().endswith(self.exclude)
        )


def _entry(paths: List[str], preferred: Sequence[str]) -> str:
    """The entry file of a multi-file artifact: the first preferred basename present, else the first path."""
    for name in preferred:
        for path in paths:
            if posixpath.basename(path) == name:
                return path
    return paths[0]


def _prepare_typespec(scratch: Path) -> Dict[str, str]:
    """Link the bundled TypeSpec libraries in (so ``import "@typespec/http"`` resolves) and isolate ``HOME``."""
    from .typespec_compile import link_typespec_libraries

    if not (scratch / "node_modules").exists():
        link_typespec_libraries(scratch)
    return {"HOME": str(scratch)}


def _prepare_node_cli(scratch: Path) -> Dict[str, str]:
    """Isolate ``HOME`` and turn off CLI telemetry for the Node toolchains (no network in the sandbox)."""
    return {"HOME": str(scratch), "REDOCLY_TELEMETRY": "off", "REDOCLY_SUPPRESS_UPDATE_NOTICE": "true"}


#: ``buf``'s documented defaults (the STANDARD lint category), written when the bundle has no ``buf.yaml``.
_BUF_YAML = "version: v2\nlint:\n  use:\n    - STANDARD\n"

_OPENAPI_EXTENSIONS = (".json", ".yaml", ".yml")

#: Every check an emitter can declare that this server knows how to run, by ``(tool, check)``.
_COMMANDS: Dict[Tuple[str, str], ToolCheckCommand] = {
    (command.tool, command.check): command
    for command in (
        ToolCheckCommand("buf", "lint", (".proto",), lambda _paths: ["lint"],
                         config_files={"buf.yaml": _BUF_YAML}),
        ToolCheckCommand("buf", "build", (".proto",), lambda _paths: ["build"],
                         config_files={"buf.yaml": _BUF_YAML}),
        ToolCheckCommand("tsp", "compile", (".tsp",),
                         lambda paths: ["compile", _entry(paths, ("main.tsp",)), "--no-emit"],
                         prepare=_prepare_typespec),
        # The emitter writes the model twice (IDL + JSON AST); building both would duplicate every shape.
        ToolCheckCommand("smithy", "build", (".smithy",),
                         lambda paths: ["build", "--output", ".smithy-build", *paths]),
        ToolCheckCommand("capnp", "compile", (".capnp",), lambda paths: ["compile", "-o-", *paths],
                         binary_stdout=True),
        ToolCheckCommand("thrift", "compile", (".thrift",),
                         lambda paths: ["-r", "-o", ".", "--gen", "json", _entry(paths, ())]),
        ToolCheckCommand("drafter", "parse", (".apib", ".md"),
                         lambda paths: ["--validate", _entry(paths, ())]),
        ToolCheckCommand("redocly", "lint", _OPENAPI_EXTENSIONS,
                         lambda paths: ["lint", _entry(paths, ("openapi.json", "openapi.yaml"))],
                         prepare=_prepare_node_cli),
        ToolCheckCommand("asyncapi", "validate", _OPENAPI_EXTENSIONS,
                         lambda paths: ["validate", _entry(paths, ("asyncapi.json", "asyncapi.yaml"))],
                         prepare=_prepare_node_cli),
    )
}


def tool_check_command(tool: str, check: str) -> Optional[ToolCheckCommand]:
    """The command that runs ``tool``'s ``check``, or ``None`` when this server has none.

    Args:
        tool: The runner tool key a declaration names (``buf``).
        check: The declared check (``lint``).

    Returns:
        The command, or ``None`` for a declaration with no runnable command.
    """
    return _COMMANDS.get((tool, check))


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------


def _safe_path(path: str) -> str:
    """``path`` as a normalized relative POSIX path, refusing anything that could escape the scratch directory.

    Raises:
        ToolCheckArtifactError: For an absolute, empty or parent-traversing path.
    """
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if not normalized or normalized in (".", "..") or normalized.startswith(("/", "../")) or ":" in normalized:
        raise ToolCheckArtifactError(f"Unsafe artifact path: {path!r}")
    return normalized


def _check_size(files: Mapping[str, str]) -> None:
    """Refuse an artifact over :data:`MAX_ARTIFACT_FILES` files or :data:`MAX_ARTIFACT_BYTES` bytes."""
    if len(files) > MAX_ARTIFACT_FILES:
        raise ToolCheckArtifactError(
            f"The artifact has {len(files)} files; a toolchain check stages at most {MAX_ARTIFACT_FILES}."
        )
    total = sum(len(text.encode("utf-8")) for text in files.values())
    if total > MAX_ARTIFACT_BYTES:
        raise ToolCheckArtifactError(
            f"The artifact is {total} bytes; a toolchain check stages at most {MAX_ARTIFACT_BYTES}."
        )


def files_from_emit(emit: EmitResult) -> ArtifactFiles:
    """The emitted files of a (re-)emit, serialized exactly as the download serves them.

    Args:
        emit: The emitter's result.

    Returns:
        Relative path → text.

    Raises:
        ToolCheckArtifactError: For an unsafe path or an oversized artifact.
    """
    from .export_job_engine import serialize_file_content

    files = {_safe_path(f.path): serialize_file_content(f.content) for f in emit.files}
    _check_size(files)
    return files


def files_from_download_body(filename: str, body: Any) -> ArtifactFiles:
    """The files of a completed export job's download: one document, or every text file of its zip.

    A bundle's own ``manifest.json`` and attestation ride along harmlessly — a check reads only the
    suffixes its command names. Binary members (not UTF-8) are skipped.

    Args:
        filename: The download filename (a single file's basename, or ``<target>.zip``).
        body: The download body — document ``str`` (single file) or zip ``bytes`` (bundle).

    Returns:
        Relative path → text.

    Raises:
        ToolCheckArtifactError: For a corrupt zip, an unsafe member path, or an oversized artifact.
    """
    if isinstance(body, str):
        files = {_safe_path(filename): body}
        _check_size(files)
        return files
    files: ArtifactFiles = {}
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                total += info.file_size
                if len(files) >= MAX_ARTIFACT_FILES or total > MAX_ARTIFACT_BYTES:
                    raise ToolCheckArtifactError(
                        f"The artifact exceeds what a toolchain check stages ({MAX_ARTIFACT_FILES} files, "
                        f"{MAX_ARTIFACT_BYTES} bytes)."
                    )
                path = _safe_path(info.filename)
                try:
                    files[path] = bundle.read(info).decode("utf-8")
                except UnicodeDecodeError:
                    continue
    except zipfile.BadZipFile as exc:
        raise ToolCheckArtifactError(f"The export job's bundle is not a readable zip: {exc}") from exc
    return files


def _stage(scratch: Path, files: Mapping[str, str], command: ToolCheckCommand) -> None:
    """Write ``files`` (and the command's default config files the artifact lacks) under ``scratch``."""
    for path, text in files.items():
        target = scratch / _safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for name, text in command.config_files.items():
        if name not in files:
            (scratch / name).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Events and result
# ---------------------------------------------------------------------------


class ExportToolCheckResult(BaseModel):
    """The outcome of one toolchain check — the console's status chip, and what attaches to the verify report."""

    model_config = ConfigDict(frozen=True)

    tool: str = Field(description="The runner tool key, e.g. ``buf``.")
    check: str = Field(description="The check, e.g. ``lint``.")
    label: str = Field(description="The declared label, e.g. ``buf lint``.")
    status: ToolCheckStatus = Field(description="How the run ended.")
    exit_code: Optional[int] = Field(
        default=None, description="The tool's exit code, or ``null`` when it did not exit on its own.",
    )
    duration_ms: int = Field(default=0, description="Wall-clock run time in milliseconds.")
    command: str = Field(description="The command as run, relative to the staged artifact (``buf lint``).")
    files: List[str] = Field(default_factory=list, description="The artifact files the check read.")
    message: Optional[str] = Field(
        default=None, description="Why the check failed to pass or run, in words; ``null`` when it passed.",
    )


def start_event(result_label: str, tool: str, check: str, command: str, files: Sequence[str]) -> Dict[str, Any]:
    """The ``start`` event: what is about to run, on which files."""
    return {"event": "start", "tool": tool, "check": check, "label": result_label, "command": command,
            "files": list(files)}


def output_event(stream: str, text: str) -> Dict[str, Any]:
    """An ``output`` event: one chunk of the tool's ``stdout`` or ``stderr``."""
    return {"event": "output", "stream": stream, "text": text}


def result_event(result: ExportToolCheckResult) -> Dict[str, Any]:
    """The closing ``result`` event, carrying the whole :class:`ExportToolCheckResult`."""
    return {"event": "result", **result.model_dump(mode="json")}


class _Scrubber:
    """Decodes a stream's chunks incrementally and hides the scratch directory's absolute path.

    A chunk boundary may split a multi-byte character (the incremental decoder handles it) or, rarely,
    the scratch path itself, in which case that one occurrence is shown unscrubbed — it names only a
    temporary directory already deleted when the run ends.
    """

    def __init__(self, scratch: Path) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        prefixes = {str(scratch), str(scratch.resolve())}
        self._prefixes = sorted(prefixes, key=len, reverse=True)

    def feed(self, chunk: bytes, final: bool = False) -> str:
        """Decode ``chunk`` and return its text with scratch paths made relative."""
        text = self._decoder.decode(chunk, final)
        for prefix in self._prefixes:
            text = text.replace(prefix + "/", "").replace(prefix, ".")
        return text


def _spec_for(tool: str) -> ToolSpec:
    """The runner spec for a check: the bundled tool's executable, override and timeout, no base args."""
    from .toolchain_packaging import bundled_tool

    bundled = bundled_tool(tool)
    return ToolSpec(
        key=tool,
        executable=bundled.executable if bundled is not None else tool,
        description=f"{tool} toolchain check (MFX-44.6).",
        default_timeout_seconds=bundled.default_timeout_seconds if bundled is not None else 60.0,
        env_override_keys=(bundled.env_override_key,) if bundled is not None else (),
        parses_json=False,
    )


async def run_tool_check(
    command: ToolCheckCommand,
    files: Mapping[str, str],
    *,
    label: str,
    on_event: EventSink,
    runner: Optional[ToolchainRunner] = None,
    timeout: Optional[float] = None,
) -> ExportToolCheckResult:
    """Run one toolchain check over an artifact, streaming its output to ``on_event``.

    Emits a ``start`` event, then an ``output`` event per chunk the tool writes, and returns the
    result (the caller sends it as the closing ``result`` event). Never raises for an outcome of
    the tool itself: a non-zero exit, a timeout or a missing binary is a result.

    Args:
        command: The check's command (:func:`tool_check_command`).
        files: The artifact: relative path → text.
        label: The declared label (``buf lint``).
        on_event: Receives each ``start`` / ``output`` event; must not block.
        runner: The toolchain runner; defaults to :data:`app.toolchain_runner.default_runner`.
        timeout: Optional per-call timeout in seconds; the tool's pinned default otherwise.

    Returns:
        The check's result.
    """
    matching = command.matching(list(files))

    def _result(status: ToolCheckStatus, display: str, message: Optional[str] = None,
                exit_code: Optional[int] = None, duration_ms: int = 0) -> ExportToolCheckResult:
        return ExportToolCheckResult(tool=command.tool, check=command.check, label=label, status=status,
                                     exit_code=exit_code, duration_ms=duration_ms, command=display,
                                     files=matching, message=message)

    if not matching:
        wanted = ", ".join(command.extensions)
        return _result(ToolCheckStatus.ERROR, label,
                       f"The artifact has no {wanted} file for {label} to check.")

    args = command.args(matching)
    display = " ".join([command.tool, *args])
    active_runner = runner if runner is not None else default_runner
    with tempfile.TemporaryDirectory(prefix=f"apiome-check-{command.tool}-") as tmp:
        scratch = Path(tmp)
        _stage(scratch, files, command)
        extra_env = command.prepare(scratch) if command.prepare is not None else None
        scrubbers = {"stdout": _Scrubber(scratch), "stderr": _Scrubber(scratch)}
        discarded = {"stdout": 0}

        def _on_output(stream: str, chunk: bytes) -> None:
            if command.binary_stdout and stream == "stdout":
                discarded["stdout"] += len(chunk)
                return
            text = scrubbers[stream].feed(chunk)
            if text:
                on_event(output_event(stream, text))

        def _flush() -> None:
            for stream, scrubber in scrubbers.items():
                tail = scrubber.feed(b"", final=True)
                if tail:
                    on_event(output_event(stream, tail))
            if discarded["stdout"]:
                on_event(output_event(
                    "stdout", f"({discarded['stdout']} bytes of binary compiler output not shown)\n"))

        on_event(start_event(label, command.tool, command.check, display, matching))
        started = time.monotonic()

        def _elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            outcome = await active_runner.run_spec(
                _spec_for(command.tool), args, timeout=timeout, cwd=str(scratch), extra_env=extra_env,
                on_output=_on_output,
            )
        except ToolNotAvailableError:
            return _result(ToolCheckStatus.UNAVAILABLE, display,
                           f"The {command.tool} toolchain is not installed on this server.")
        except ToolExecutionError as exc:
            _flush()
            return _result(ToolCheckStatus.FAILED, display, f"{label} exited {exc.exit_code}.",
                           exit_code=exc.exit_code, duration_ms=_elapsed())
        except ToolTimeoutError as exc:
            _flush()
            return _result(ToolCheckStatus.TIMED_OUT, display,
                           f"{label} exceeded its {exc.timeout_seconds:g}s timeout and was stopped.",
                           duration_ms=_elapsed())
        except (ToolOutputTooLargeError, ToolResourceLimitError) as exc:
            _flush()
            return _result(ToolCheckStatus.ERROR, display, str(exc), duration_ms=_elapsed())
        except ToolchainError as exc:
            _flush()
            return _result(ToolCheckStatus.ERROR, display, f"{label} could not run: {exc}",
                           duration_ms=_elapsed())
        _flush()
        return _result(ToolCheckStatus.PASSED, display, exit_code=outcome.exit_code,
                       duration_ms=outcome.duration_ms)
