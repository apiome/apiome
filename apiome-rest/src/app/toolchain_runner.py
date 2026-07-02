"""Polyglot toolchain runner service — MFI-5.1 (#3750).

Many of the authoritative parsers/linters/diff tools the multi-format import roadmap
needs are **not Python** — ``buf`` (protobuf), ``tsp`` (TypeSpec), ``smithy``, ``drafter``
(API Blueprint), AMF (RAML, JVM), the AsyncAPI CLI, graphql-inspector. Each format
adapter must be able to shell out to one and get **structured output back**, the same
way every time. This module is that seam: a small service that runs a *registered* tool
(by key + args) in a **constrained subprocess**, captures stdout/stderr/exit, parses the
tool's JSON, enforces a per-call timeout, raises typed errors, and caps how many tool
processes run at once.

Scope (MFI-5.1 only):

* **tool registry** — :class:`ToolSpec` describes a tool (key, executable, default
  leading args, default timeout, env overrides); :func:`register_tool` /
  :func:`get_tool` / :func:`available_tools` / :func:`describe_tools` mirror the
  ImportSource registry (MFI-1.1) so UI/CLI/REST can enumerate what is wired up.
* **runner** — :class:`ToolchainRunner` runs a spec in an ``asyncio`` subprocess with a
  sanitized environment (no inherited DB URL / secrets), an explicit argv (never a
  shell), a per-call timeout that *kills* the process, JSON parsing of stdout, and a
  global concurrency cap (an :class:`asyncio.Semaphore`).
* **structured errors** — :class:`ToolchainError` subclasses for every failure mode
  (unknown tool, missing executable, timeout, non-zero exit, non-JSON output), each
  carrying the tool key so a caller can surface a clean message.

Companion tickets in MFI-EPIC-5:

* bundling/pinning the actual tool binaries into the runtime image — **MFI-5.2**
  (:mod:`app.toolchain_packaging`);
* OS-level sandboxing — no-network default, ``setrlimit`` CPU/memory/file-size/process
  clamps, and input/output size caps — **MFI-5.3** (:mod:`app.toolchain_sandbox`). Every run
  carries a :class:`~app.toolchain_sandbox.SandboxPolicy` (the runner's
  :attr:`ToolchainRunner.default_policy`, overridable per call): the subprocess is launched
  in an isolated network namespace, its resources are clamped via a ``preexec_fn``, an
  oversized ``stdin`` is rejected before spawning, and runaway output is killed mid-stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .config import settings
from .toolchain_sandbox import SandboxPolicy, build_preexec_fn

logger = logging.getLogger(__name__)

__all__ = [
    "ToolSpec",
    "ToolDescriptor",
    "ToolRunResult",
    "ToolchainError",
    "ToolNotRegisteredError",
    "ToolNotAvailableError",
    "ToolTimeoutError",
    "ToolExecutionError",
    "ToolOutputError",
    "ToolInputTooLargeError",
    "ToolOutputTooLargeError",
    "ToolResourceLimitError",
    "ToolSandboxError",
    "ToolchainRunner",
    "SandboxPolicy",
    "register_tool",
    "is_tool_available",
    "get_tool",
    "available_tools",
    "describe_tools",
    "resolve_executable",
    "default_runner",
    "run_tool",
    "SAMPLE_ECHO_TOOL_KEY",
]


# ===========================================================================
# Structured errors
# ===========================================================================


class ToolchainError(Exception):
    """Base class for every toolchain-runner failure.

    Carries the offending tool ``key`` so a caller (an import adapter) can surface a
    clean, tool-attributed message instead of a raw traceback.
    """

    def __init__(self, key: str, message: str) -> None:
        self.key = key
        super().__init__(message)


class ToolNotRegisteredError(ToolchainError):
    """Raised when a run targets a tool key that is not in the registry."""

    def __init__(self, key: str) -> None:
        super().__init__(key, f"No toolchain tool registered under key {key!r}")


class ToolNotAvailableError(ToolchainError):
    """Raised when a registered tool's executable is not present on the host.

    This is the "format unavailable" path the runtime-packaging ticket (MFI-5.2) keys
    off: the tool is *known* but its binary was not installed/bundled.
    """

    def __init__(self, key: str, executable: str) -> None:
        self.executable = executable
        super().__init__(
            key,
            f"Executable {executable!r} for tool {key!r} was not found on PATH; "
            "the tool is not installed in this runtime (see MFI-5.2 tool packaging).",
        )


class ToolTimeoutError(ToolchainError):
    """Raised when a tool exceeds its per-call timeout (the process is killed)."""

    def __init__(self, key: str, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(
            key, f"Tool {key!r} exceeded its {timeout_seconds:g}s timeout and was killed"
        )


class ToolExecutionError(ToolchainError):
    """Raised when a tool exits non-zero. Carries exit code + captured streams."""

    def __init__(self, key: str, exit_code: int, stdout: str, stderr: str) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        detail = stderr.strip() or stdout.strip() or "(no output)"
        super().__init__(key, f"Tool {key!r} exited {exit_code}: {detail[:500]}")


class ToolOutputError(ToolchainError):
    """Raised when a tool's stdout was expected to be JSON but could not be parsed."""

    def __init__(self, key: str, stdout: str, reason: str) -> None:
        self.stdout = stdout
        self.reason = reason
        super().__init__(key, f"Tool {key!r} did not return valid JSON: {reason}")


class ToolInputTooLargeError(ToolchainError):
    """Raised when a tool's ``stdin`` exceeds the sandbox input-size cap (MFI-5.3).

    The oversized input is rejected *before* the tool is spawned, so a hostile/huge document
    never reaches a third-party CLI.
    """

    def __init__(self, key: str, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(
            key,
            f"Tool {key!r} input is {size} bytes, exceeding the {limit}-byte sandbox limit",
        )


class ToolOutputTooLargeError(ToolchainError):
    """Raised when a tool's combined stdout+stderr exceeds the sandbox output cap (MFI-5.3).

    The process is killed mid-stream so a zip-bomb / runaway tool can never exhaust memory.
    """

    def __init__(self, key: str, limit: int) -> None:
        self.limit = limit
        super().__init__(
            key,
            f"Tool {key!r} output exceeded the {limit}-byte sandbox limit and was killed",
        )


class ToolResourceLimitError(ToolchainError):
    """Raised when a tool was killed by the kernel for breaching a resource limit (MFI-5.3).

    Covers the CPU-time cap (``SIGXCPU``) and the file-size cap (``SIGXFSZ``).
    """

    def __init__(self, key: str, signal_name: str, detail: str) -> None:
        self.signal_name = signal_name
        super().__init__(key, f"Tool {key!r} hit a resource limit ({signal_name}): {detail}")


class ToolSandboxError(ToolchainError):
    """Raised when the constrained subprocess could not be established (MFI-5.3).

    The dominant cause is strict network-isolation enforcement on a host where the kernel
    refuses the namespace (unprivileged user namespaces disabled): the runner fails closed
    rather than run a tool with network access it cannot remove.
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(key, f"Tool {key!r} sandbox could not be established: {reason}")


# ===========================================================================
# Tool specification, descriptor & result
# ===========================================================================

# Environment variables passed through to a tool subprocess. Everything else (notably
# DATABASE_URL, JWT secrets, cloud credentials) is dropped so a third-party CLI run over
# user-supplied input never sees the service's ambient secrets. A tool may widen this with
# its own ``env_passthrough`` for vars it genuinely needs (e.g. a tool cache dir).
_BASE_ENV_PASSTHROUGH: Tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",  # Windows: many runtimes fail to start without it
    # The service's own dynamic-linker search path — not a secret. A tool (or
    # interpreter) built with a shared runtime located via this path can't even
    # start without it (e.g. a `--enable-shared` python fails to load
    # libpython*.so), so forward it; it points only at the trusted image's libs.
    "LD_LIBRARY_PATH",
)


@dataclass(frozen=True)
class ToolSpec:
    """How to invoke one external tool.

    Attributes:
        key: Stable registry key, e.g. ``"buf"`` / ``"tsp"`` / ``"smithy"``.
        executable: Program to run — a bare name resolved on ``PATH`` (e.g. ``"buf"``)
            or an absolute path. Resolution can be overridden at run time via any of
            ``env_override_keys``.
        description: One-line human description for the source/tool listing.
        base_args: Leading arguments always prepended before a caller's per-call args
            (e.g. ``("build", "--output", "-")``).
        default_timeout_seconds: Per-call wall-clock ceiling used when a caller passes no
            explicit timeout; ``None`` falls back to the service default.
        env_override_keys: Environment variables that, when set, override ``executable``
            with an absolute path (so a deployment can point at a bundled binary).
        env_passthrough: Extra environment variable names to forward into the subprocess
            on top of :data:`_BASE_ENV_PASSTHROUGH`.
        parses_json: Whether the tool's stdout is JSON the runner should parse. ``False``
            for tools whose useful output is non-JSON (the raw stdout is still returned).
    """

    key: str
    executable: str
    description: str = ""
    base_args: Tuple[str, ...] = ()
    default_timeout_seconds: Optional[float] = None
    env_override_keys: Tuple[str, ...] = ()
    env_passthrough: Tuple[str, ...] = ()
    parses_json: bool = True


class ToolDescriptor(BaseModel):
    """Serializable, public view of a registered tool for enumeration."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(description="Stable registry key, e.g. ``buf``.")
    executable: str = Field(description="Program name or path the runner invokes.")
    description: str = Field(description="One-line description of the tool.")
    base_args: List[str] = Field(
        default_factory=list, description="Leading args always prepended to a call."
    )
    default_timeout_seconds: Optional[float] = Field(
        default=None, description="Per-call timeout default, when the tool pins one."
    )
    parses_json: bool = Field(description="Whether the runner parses stdout as JSON.")


class ToolRunResult(BaseModel):
    """The structured outcome of one successful (exit 0) tool invocation."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(description="The tool key that ran.")
    argv: List[str] = Field(description="The full argv the subprocess was spawned with.")
    exit_code: int = Field(description="Process exit code (always 0 for a success).")
    stdout: str = Field(description="Captured standard output (decoded UTF-8).")
    stderr: str = Field(description="Captured standard error (decoded UTF-8).")
    parsed_json: Optional[Any] = Field(
        default=None,
        description="Parsed JSON from stdout when the tool ``parses_json`` (else ``None``).",
    )
    duration_ms: int = Field(description="Wall-clock duration of the call in milliseconds.")


# ===========================================================================
# Registry
# ===========================================================================

# Key → spec registry. A format epic registers the tool(s) it shells out to so the runner
# (and UI/CLI/REST enumeration) can resolve them by key without importing each adapter.
_REGISTRY: Dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> ToolSpec:
    """Register a :class:`ToolSpec` under its :attr:`ToolSpec.key`.

    Args:
        spec: The tool specification to register.

    Returns:
        ``spec`` unchanged, so this can be used inline.

    Raises:
        ValueError: If ``spec.key`` is empty, or a *different* spec is already
            registered under the same key (re-registering an equal spec is a no-op so
            module re-import is safe).
    """
    if not spec.key:
        raise ValueError("ToolSpec.key must be a non-empty string to register")
    if not spec.executable:
        raise ValueError(f"ToolSpec {spec.key!r} must set a non-empty executable")
    existing = _REGISTRY.get(spec.key)
    if existing is not None and existing != spec:
        raise ValueError(
            f"tool {spec.key!r} already registered with a different spec; "
            "cannot re-register"
        )
    _REGISTRY[spec.key] = spec
    return spec


def get_tool(key: str) -> Optional[ToolSpec]:
    """Return the :class:`ToolSpec` registered under ``key``, or ``None``."""
    _load_builtin_tools()
    return _REGISTRY.get(key)


def is_tool_available(key: str) -> bool:
    """Whether a registered tool's executable can be resolved in this runtime (MFI-5.2).

    Non-raising: an unknown tool key or an unresolvable executable both return ``False``. This is the
    availability probe the import-source descriptors use to report whether a format whose parser
    shells out to a bundled binary (e.g. ``buf`` for gRPC/Protobuf) can actually run here.
    """
    spec = get_tool(key)
    if spec is None:
        return False
    return resolve_executable(spec) is not None


def available_tools() -> List[str]:
    """Return the sorted list of registered tool keys."""
    _load_builtin_tools()
    return sorted(_REGISTRY)


def describe_tools() -> List[ToolDescriptor]:
    """Return every registered tool's descriptor, sorted by key."""
    _load_builtin_tools()
    return [_descriptor_for(_REGISTRY[key]) for key in sorted(_REGISTRY)]


def _descriptor_for(spec: ToolSpec) -> ToolDescriptor:
    return ToolDescriptor(
        key=spec.key,
        executable=spec.executable,
        description=spec.description,
        base_args=list(spec.base_args),
        default_timeout_seconds=spec.default_timeout_seconds,
        parses_json=spec.parses_json,
    )


# ===========================================================================
# Runner
# ===========================================================================


def resolve_executable(spec: ToolSpec) -> Optional[str]:
    """Resolve a tool's executable to a runnable path, or ``None`` if not resolvable.

    An ``env_override_keys`` value wins (a deployment can point at a bundled binary);
    otherwise an absolute/existing path is used as-is, else the name is resolved on
    ``PATH``. This is the **non-raising** resolver behind both the runner's strict
    :func:`_resolve_executable` and the MFI-5.2 availability probe (which needs to report
    "unavailable" without raising).
    """
    for env_key in spec.env_override_keys:
        override = (os.environ.get(env_key) or "").strip()
        if override:
            return override

    candidate = spec.executable
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate

    return shutil.which(candidate)


def _resolve_executable(spec: ToolSpec) -> str:
    """Resolve a tool's executable to a runnable path, raising when absent.

    Raises:
        ToolNotAvailableError: If nothing resolves to an executable on this host.
    """
    resolved = resolve_executable(spec)
    if resolved:
        return resolved
    raise ToolNotAvailableError(spec.key, spec.executable)


def _build_subprocess_env(spec: ToolSpec, extra_env: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Build the sanitized environment for a tool subprocess.

    Only an allow-list of host variables is forwarded (plus the tool's declared
    ``env_passthrough`` and any caller ``extra_env``), so ambient secrets never reach a
    third-party CLI.
    """
    allowed = (*_BASE_ENV_PASSTHROUGH, *spec.env_passthrough)
    env: Dict[str, str] = {
        name: os.environ[name] for name in allowed if name in os.environ
    }
    if extra_env:
        env.update(extra_env)
    return env


class ToolchainRunner:
    """Runs registered tools in constrained subprocesses, capped at N concurrent.

    One shared instance (:data:`default_runner`) backs the whole service; the concurrency
    cap is process-wide so a burst of imports cannot fork-bomb the host. The cap is
    enforced with an :class:`asyncio.Semaphore`; excess calls queue and run as slots free.
    """

    def __init__(
        self,
        max_concurrency: int,
        default_timeout_seconds: float,
        default_policy: Optional[SandboxPolicy] = None,
    ) -> None:
        """Create a runner.

        Args:
            max_concurrency: Maximum tool subprocesses allowed to run simultaneously
                (clamped to at least 1).
            default_timeout_seconds: Per-call timeout used when neither the call nor the
                tool spec pins one.
            default_policy: The sandbox policy applied to every run that does not pass its
                own (MFI-5.3). Defaults to :meth:`SandboxPolicy.from_settings` — no network,
                resource limits, and input/output caps from configuration.
        """
        self.max_concurrency = max(1, int(max_concurrency))
        self.default_timeout_seconds = float(default_timeout_seconds)
        self.default_policy = default_policy or SandboxPolicy.from_settings()
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        # Live/peak in-flight counters, for observability and the concurrency-cap tests.
        self._active = 0
        self._peak_active = 0

    @property
    def active(self) -> int:
        """How many tool subprocesses are running right now."""
        return self._active

    @property
    def peak_active(self) -> int:
        """The high-water mark of simultaneously-running tool subprocesses."""
        return self._peak_active

    async def run(
        self,
        key: str,
        args: Sequence[str] = (),
        *,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        policy: Optional[SandboxPolicy] = None,
    ) -> ToolRunResult:
        """Run a registered tool by ``key`` with ``args`` and return its result.

        Raises:
            ToolNotRegisteredError: If ``key`` is not registered.
            ToolNotAvailableError / ToolTimeoutError / ToolExecutionError / ToolOutputError /
            ToolInputTooLargeError / ToolOutputTooLargeError / ToolResourceLimitError /
            ToolSandboxError: See :meth:`run_spec`.
        """
        spec = get_tool(key)
        if spec is None:
            raise ToolNotRegisteredError(key)
        return await self.run_spec(
            spec, args, stdin=stdin, timeout=timeout, cwd=cwd, extra_env=extra_env, policy=policy
        )

    async def run_spec(
        self,
        spec: ToolSpec,
        args: Sequence[str] = (),
        *,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        policy: Optional[SandboxPolicy] = None,
    ) -> ToolRunResult:
        """Run a tool described by ``spec`` (no registry lookup) and return its result.

        The subprocess is spawned with an explicit argv (never a shell), a sanitized
        environment, an optional working directory, and the sandbox constraints of ``policy``
        (MFI-5.3): no network by default, ``setrlimit`` CPU/memory/file-size/process clamps,
        and input/output size caps. Its stdout/stderr are captured with a per-call timeout;
        on timeout the process is killed.

        Args:
            spec: The tool specification to run.
            args: Per-call arguments appended after ``spec.base_args``.
            stdin: Optional text written to the process's standard input.
            timeout: Per-call timeout in seconds; falls back to the spec default, then
                the runner default.
            cwd: Optional working directory for the subprocess.
            extra_env: Optional environment overrides merged onto the sanitized env.
            policy: Sandbox policy for this call; falls back to the runner's
                :attr:`default_policy`.

        Returns:
            A :class:`ToolRunResult` with exit code, captured streams, parsed JSON (when
            ``spec.parses_json``), and the call duration.

        Raises:
            ToolNotAvailableError: The executable was not found on the host.
            ToolInputTooLargeError: ``stdin`` exceeded the policy's input-size cap.
            ToolTimeoutError: The call exceeded its timeout (process killed).
            ToolOutputTooLargeError: The tool's output exceeded the policy's output cap.
            ToolResourceLimitError: The tool was killed by the kernel for a CPU/file-size cap.
            ToolExecutionError: The tool exited non-zero.
            ToolOutputError: ``spec.parses_json`` but stdout was not valid JSON.
            ToolSandboxError: The constrained subprocess could not be established
                (strict network isolation on an unsupported host).
        """
        effective_policy = policy or self.default_policy
        executable = _resolve_executable(spec)
        argv: List[str] = [executable, *spec.base_args, *args]
        env = _build_subprocess_env(spec, extra_env)
        effective_timeout = float(
            timeout
            if timeout is not None
            else (
                spec.default_timeout_seconds
                if spec.default_timeout_seconds is not None
                else self.default_timeout_seconds
            )
        )
        stdin_bytes = stdin.encode("utf-8") if stdin is not None else None

        # Reject an oversized input *before* spawning anything — a hostile/huge document must
        # never reach the third-party CLI (MFI-5.3 acceptance: oversized inputs rejected).
        if (
            effective_policy.max_input_bytes is not None
            and stdin_bytes is not None
            and len(stdin_bytes) > effective_policy.max_input_bytes
        ):
            raise ToolInputTooLargeError(
                spec.key, len(stdin_bytes), effective_policy.max_input_bytes
            )

        async with self._semaphore:
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            started = time.monotonic()
            try:
                return await self._spawn_and_capture(
                    spec, argv, env, cwd, stdin_bytes, effective_timeout, started, effective_policy
                )
            finally:
                self._active -= 1

    async def _spawn_and_capture(
        self,
        spec: ToolSpec,
        argv: List[str],
        env: Dict[str, str],
        cwd: Optional[str],
        stdin_bytes: Optional[bytes],
        timeout_seconds: float,
        started: float,
        policy: SandboxPolicy,
    ) -> ToolRunResult:
        """Spawn the constrained subprocess, capture its (capped) output, build the result."""
        logger.info(
            "toolchain run key=%s argv=%s timeout=%.1fs no_network=%s",
            spec.key,
            argv,
            timeout_seconds,
            policy.isolates_network,
        )
        # POSIX-only: the rlimit/namespace clamps run in the forked child before exec.
        preexec_fn = build_preexec_fn(policy)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                preexec_fn=preexec_fn,
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            # The executable resolved but vanished between resolution and spawn, or cwd is
            # bad — treat as "tool not available" with the underlying reason.
            raise ToolNotAvailableError(spec.key, spec.executable) from exc
        except subprocess.SubprocessError as exc:
            # A preexec_fn failure (CPython transfers it as a SubprocessError) — in practice
            # strict network isolation refused by the kernel. Fail closed.
            raise ToolSandboxError(spec.key, str(exc)) from exc

        max_output = policy.max_output_bytes
        try:
            stdout_b, stderr_b, output_exceeded = await asyncio.wait_for(
                self._capture(proc, stdin_bytes, max_output), timeout=timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            await self._terminate_and_reap(proc, spec.key)
            raise ToolTimeoutError(spec.key, timeout_seconds) from exc

        # _capture drained both pipes to EOF (killing the tool first if the output cap was
        # blown), so the transports have disconnected and this reap settles the return code
        # without blocking.
        await proc.wait()

        if output_exceeded:
            raise ToolOutputTooLargeError(spec.key, max_output)

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else -1

        # A negative return code is death by signal. Surface the kernel's resource-limit kills
        # (CPU / file-size) as a dedicated error so callers can tell a clamp from a tool bug.
        if exit_code < 0:
            self._raise_for_signal(spec.key, -exit_code, stdout, stderr, exit_code)

        if exit_code != 0:
            raise ToolExecutionError(spec.key, exit_code, stdout, stderr)

        parsed: Optional[Any] = None
        if spec.parses_json:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise ToolOutputError(spec.key, stdout, str(exc)) from exc

        return ToolRunResult(
            key=spec.key,
            argv=argv,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            parsed_json=parsed,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _raise_for_signal(
        key: str, signal_num: int, stdout: str, stderr: str, exit_code: int
    ) -> None:
        """Map a signal-kill to a resource-limit error (CPU/file-size) or an execution error."""
        try:
            name = signal.Signals(signal_num).name
        except ValueError:  # pragma: no cover - unknown signal number
            name = f"signal {signal_num}"
        resource_signals = {getattr(signal, "SIGXCPU", None), getattr(signal, "SIGXFSZ", None)}
        if signal_num in {s.value for s in resource_signals if s is not None}:
            detail = stderr.strip() or stdout.strip() or "(no output)"
            raise ToolResourceLimitError(key, name, detail[:500])
        raise ToolExecutionError(key, exit_code, stdout, stderr)

    async def _capture(
        self,
        proc: "asyncio.subprocess.Process",
        stdin_bytes: Optional[bytes],
        max_output_bytes: Optional[int],
    ) -> Tuple[bytes, bytes, bool]:
        """Feed stdin and drain stdout/stderr concurrently, capping the *retained* output.

        Returns ``(stdout, stderr, exceeded)``. ``exceeded`` is ``True`` once the *combined*
        stdout+stderr crosses ``max_output_bytes``; past that point output is no longer
        retained (so a runaway tool cannot blow memory) and the tool is killed to bound how
        much more it can produce — but both pipes are still **drained to EOF**. That last part
        is load-bearing: :meth:`asyncio.subprocess.Process.wait` resolves only once every pipe
        transport has disconnected, so a *paused* (unread) pipe would otherwise wedge the
        subsequent reap. This replaces :meth:`~asyncio.subprocess.Process.communicate` so the
        cap can bite while still keeping the reap safe.
        """
        # Shared budget across both streams; asyncio is single-threaded so reads interleave
        # only at await points — a plain mutable counter is safe (no lock needed).
        state = {"total": 0, "killed": False}
        out_chunks: List[bytes] = []
        err_chunks: List[bytes] = []

        async def _feed() -> None:
            if proc.stdin is None:
                return
            try:
                if stdin_bytes:
                    proc.stdin.write(stdin_bytes)
                    await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass  # the tool closed stdin early; not our problem to surface
            finally:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        def _kill_once() -> None:
            if not state["killed"]:
                state["killed"] = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass  # already gone

        async def _drain(stream: Optional["asyncio.StreamReader"], sink: List[bytes]) -> None:
            if stream is None:
                return
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break  # EOF — the pipe transport disconnects, unblocking the later wait()
                state["total"] += len(chunk)
                if max_output_bytes is None or state["total"] <= max_output_bytes:
                    sink.append(chunk)
                else:
                    # Over the cap: stop retaining and kill the tool to bound further output,
                    # but keep reading to EOF so the pipe transport disconnects cleanly.
                    _kill_once()

        # Feed stdin and drain both pipes concurrently — draining serially around a write would
        # deadlock a tool that floods stdout before reading all of stdin (the classic pipe
        # deadlock ``communicate`` exists to avoid).
        feed_task = asyncio.ensure_future(_feed())
        out_task = asyncio.ensure_future(_drain(proc.stdout, out_chunks))
        err_task = asyncio.ensure_future(_drain(proc.stderr, err_chunks))
        all_tasks = (out_task, err_task, feed_task)
        try:
            await asyncio.gather(out_task, err_task)
            exceeded = max_output_bytes is not None and state["total"] > max_output_bytes
            return b"".join(out_chunks), b"".join(err_chunks), exceeded
        finally:
            # Safety net for the outer-timeout path: cancel anything still running (the stdin
            # feeder, or every task if ``wait_for`` cancelled us) and reap so nothing dangles.
            for task in all_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)

    async def _terminate_and_reap(self, proc: "asyncio.subprocess.Process", key: str) -> None:
        """Kill a process, drain any buffered pipe output, then reap it (best effort).

        Used on the timeout path, where the capture drains were cancelled before reaching EOF.
        Draining the pipes first matters: ``wait`` resolves only once every pipe transport has
        disconnected, so a paused/unread pipe would otherwise hang the reap.
        """
        try:
            proc.kill()
        except ProcessLookupError:
            pass  # already gone

        async def _flush(stream: Optional["asyncio.StreamReader"]) -> None:
            if stream is None:
                return
            try:
                while await stream.read(65536):
                    pass
            except Exception:  # noqa: BLE001 - best-effort drain; we are tearing the process down
                pass

        await asyncio.gather(_flush(proc.stdout), _flush(proc.stderr), return_exceptions=True)
        try:
            await proc.wait()
        except Exception:  # noqa: BLE001 - best-effort reap; the kill already happened
            logger.debug("toolchain reap-after-kill failed key=%s", key, exc_info=True)


# ===========================================================================
# Built-in sample tool + default runner
# ===========================================================================

#: Registry key of the built-in sample tool — a portable JSON echo used as the
#: acceptance vehicle (and the smallest worked example) so the runner can be exercised
#: end-to-end without bundling a real external CLI (that is MFI-5.2).
SAMPLE_ECHO_TOOL_KEY = "sample-echo"

# A tiny, dependency-free script run via the current Python interpreter: it echoes a JSON
# object describing the args it received and any stdin, so a caller gets parsed JSON back.
_SAMPLE_ECHO_SCRIPT = (
    "import json,sys;"
    "sys.stdout.write(json.dumps({"
    "'tool':'sample-echo','args':sys.argv[1:],'stdin':sys.stdin.read()}))"
)

_builtins_loaded = False


def _load_builtin_tools() -> None:
    """Register the built-in sample tool once (idempotent and cheap)."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    register_tool(
        ToolSpec(
            key=SAMPLE_ECHO_TOOL_KEY,
            executable=sys.executable,
            description="Portable JSON echo (reference tool for the toolchain runner).",
            base_args=("-c", _SAMPLE_ECHO_SCRIPT),
            default_timeout_seconds=15.0,
            parses_json=True,
        )
    )
    # Also register the real bundled tools (buf, tsp, smithy, …) so they resolve by key
    # through the same registry. Imported lazily to avoid an import cycle (the packaging
    # module imports this one); a failure here must never break the runner, so it is logged
    # and swallowed — the bundled tools simply will not be enumerable until import succeeds.
    try:
        from . import toolchain_packaging

        toolchain_packaging.register_bundled_tools()
    except Exception:  # noqa: BLE001 - best-effort; the sample tool still works without these
        logger.warning("failed to register bundled toolchain tools", exc_info=True)


#: The process-wide runner. Its concurrency cap and default timeout come from settings so
#: a deployment can tune them without code changes.
default_runner = ToolchainRunner(
    max_concurrency=settings.toolchain_max_concurrency,
    default_timeout_seconds=settings.toolchain_default_timeout_seconds,
)


async def run_tool(
    key: str,
    args: Sequence[str] = (),
    *,
    stdin: Optional[str] = None,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    extra_env: Optional[Dict[str, str]] = None,
    policy: Optional[SandboxPolicy] = None,
) -> ToolRunResult:
    """Run a registered tool on the shared :data:`default_runner` (module convenience)."""
    return await default_runner.run(
        key, args, stdin=stdin, timeout=timeout, cwd=cwd, extra_env=extra_env, policy=policy
    )
