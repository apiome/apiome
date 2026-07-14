"""Restricted runner façade for external-linter adapters (CLX-2.1, #4851).

Wraps :class:`~app.toolchain_runner.ToolchainRunner` so every adapter command
runs with bounded input/resources, an explicit argv (never a shell), the default
no-network :class:`~app.toolchain_sandbox.SandboxPolicy`, and logging that never
emits secret-bearing env values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .lint_evidence import (
    OUTCOME_BLOCKED_BY_POLICY,
    OUTCOME_FAILED,
    OUTCOME_UNAVAILABLE,
)
from .toolchain_runner import (
    ToolchainError,
    ToolchainRunner,
    ToolExecutionError,
    ToolInputTooLargeError,
    ToolNotAvailableError,
    ToolNotRegisteredError,
    ToolOutputError,
    ToolOutputTooLargeError,
    ToolResourceLimitError,
    ToolSandboxError,
    ToolSpec,
    ToolTimeoutError,
    default_runner,
)
from .toolchain_sandbox import SandboxPolicy

logger = logging.getLogger(__name__)

__all__ = [
    "RestrictedRunner",
    "RestrictedRunSuccess",
    "RestrictedRunFailure",
    "AdapterFailureKind",
    "FAILURE_UNAVAILABLE",
    "FAILURE_TIMEOUT",
    "FAILURE_CRASH",
    "FAILURE_MALFORMED",
    "FAILURE_FAILED",
    "FAILURE_BLOCKED_BY_POLICY",
    "failure_kind_to_outcome",
    "redact_env_for_log",
    "redact_argv_for_log",
    "default_restricted_runner",
]

FAILURE_UNAVAILABLE = "unavailable"
FAILURE_TIMEOUT = "timeout"
FAILURE_CRASH = "crash"
FAILURE_MALFORMED = "malformed"
FAILURE_FAILED = "failed"
FAILURE_BLOCKED_BY_POLICY = "blocked_by_policy"

AdapterFailureKind = str

#: Substring markers matching :mod:`app.lint_evidence` secret-key redaction.
_SECRET_KEY_MARKERS = ("secret", "token", "password", "credential", "api_key", "apikey")


@dataclass(frozen=True)
class RestrictedRunSuccess:
    """Successful restricted tool invocation (exit 0 from the toolchain runner)."""

    key: str
    argv: Tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


@dataclass(frozen=True)
class RestrictedRunFailure:
    """Operational failure classified for evidence coverage.

    Attributes:
        kind: One of the ``FAILURE_*`` constants.
        key: Tool key that failed.
        message: Short, non-secret diagnostic message.
        exit_code: Process exit code when known.
        stdout: Captured stdout (not for logs; for parsers/violation exits).
        stderr: Captured stderr (not for logs).
        argv: Redacted argv snapshot for diagnostics.
    """

    kind: AdapterFailureKind
    key: str
    message: str
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    argv: Tuple[str, ...] = ()


def failure_kind_to_outcome(kind: AdapterFailureKind) -> str:
    """Map an adapter failure kind onto a CLX-1.1 evidence outcome."""
    if kind == FAILURE_UNAVAILABLE:
        return OUTCOME_UNAVAILABLE
    if kind == FAILURE_BLOCKED_BY_POLICY:
        return OUTCOME_BLOCKED_BY_POLICY
    return OUTCOME_FAILED


def redact_env_for_log(env: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """Return a copy of ``env`` with secret-bearing keys replaced by a sentinel."""
    if not env:
        return {}
    out: Dict[str, str] = {}
    for key, value in env.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_KEY_MARKERS):
            out[key] = "<redacted>"
        else:
            out[key] = value
    return out


def redact_argv_for_log(argv: Sequence[str]) -> List[str]:
    """Return argv safe for logs (pass-through; secrets must not be placed in argv)."""
    return [str(part) for part in argv]


class RestrictedRunner:
    """Thin façade over :class:`ToolchainRunner` for external-linter adapters.

    Every call uses an explicit argv, the effective sandbox policy (default
    no-network), and redacted logging. Callers receive either
    :class:`RestrictedRunSuccess` or :class:`RestrictedRunFailure` — never a
    bare toolchain exception — so adapters can map failures into coverage evidence.
    """

    def __init__(
        self,
        inner: Optional[ToolchainRunner] = None,
        *,
        default_policy: Optional[SandboxPolicy] = None,
    ) -> None:
        self._inner = inner if inner is not None else default_runner
        self._default_policy = default_policy

    @property
    def inner(self) -> ToolchainRunner:
        """The wrapped toolchain runner (injectable for tests)."""
        return self._inner

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
        accept_exit_codes: Sequence[int] = (),
    ) -> RestrictedRunSuccess | RestrictedRunFailure:
        """Run ``spec`` under sandbox constraints; classify toolchain failures.

        Args:
            spec: Tool specification (argv is never a shell).
            args: Per-call arguments after ``spec.base_args``.
            stdin: Optional stdin text (subject to input-size caps).
            timeout: Optional wall-clock timeout override.
            cwd: Optional working directory.
            extra_env: Optional env overrides (secret keys are redacted in logs).
            policy: Sandbox policy; defaults to the runner / façade default.
            accept_exit_codes: Non-zero exit codes treated as success when stdout
                is still useful (e.g. Buf lint exit ``100`` for violations). When
                such an exit occurs, returns :class:`RestrictedRunSuccess` with
                that exit code so the adapter can parse findings.

        Returns:
            :class:`RestrictedRunSuccess` or :class:`RestrictedRunFailure`.
        """
        effective_policy = policy or self._default_policy or getattr(
            self._inner, "default_policy", None
        )
        redacted_env = redact_env_for_log(extra_env)
        preview_argv = redact_argv_for_log(
            [spec.executable, *spec.base_args, *args]
        )
        logger.info(
            "restricted_runner.start tool=%s argv=%s env=%s timeout=%s",
            spec.key,
            preview_argv,
            redacted_env,
            timeout,
        )

        try:
            result = await self._inner.run_spec(
                spec,
                args,
                stdin=stdin,
                timeout=timeout,
                cwd=cwd,
                extra_env=extra_env,
                policy=effective_policy,
            )
        except ToolNotAvailableError as exc:
            return self._fail(
                FAILURE_UNAVAILABLE, spec.key, str(exc), argv=preview_argv
            )
        except ToolNotRegisteredError as exc:
            return self._fail(
                FAILURE_UNAVAILABLE, spec.key, str(exc), argv=preview_argv
            )
        except ToolTimeoutError as exc:
            return self._fail(
                FAILURE_TIMEOUT, spec.key, str(exc), argv=preview_argv
            )
        except ToolSandboxError as exc:
            return self._fail(
                FAILURE_BLOCKED_BY_POLICY, spec.key, str(exc), argv=preview_argv
            )
        except (ToolInputTooLargeError, ToolOutputTooLargeError, ToolResourceLimitError) as exc:
            return self._fail(
                FAILURE_FAILED, spec.key, str(exc), argv=preview_argv
            )
        except ToolOutputError as exc:
            return self._fail(
                FAILURE_MALFORMED,
                spec.key,
                str(exc),
                stdout=getattr(exc, "stdout", "") or "",
                argv=preview_argv,
            )
        except ToolExecutionError as exc:
            if exc.exit_code in accept_exit_codes:
                return RestrictedRunSuccess(
                    key=spec.key,
                    argv=tuple(preview_argv),
                    exit_code=exc.exit_code,
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                    duration_ms=0,
                )
            # Non-accepted non-zero exit: treat as crash/operational failure.
            # Adapters that need "violations via exit code" must list that code
            # in accept_exit_codes.
            return self._fail(
                FAILURE_CRASH,
                spec.key,
                str(exc),
                exit_code=exc.exit_code,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                argv=preview_argv,
            )
        except ToolchainError as exc:
            return self._fail(
                FAILURE_FAILED, spec.key, str(exc), argv=preview_argv
            )

        duration_ms = int(getattr(result, "duration_ms", 0) or 0)
        logger.info(
            "restricted_runner.ok tool=%s exit=%s duration_ms=%s",
            getattr(result, "key", spec.key),
            result.exit_code,
            duration_ms,
        )
        return RestrictedRunner._success_from_result(
            result, preview_argv, fallback_key=spec.key
        )

    @staticmethod
    def _success_from_result(
        result: Any,
        preview_argv: Sequence[str],
        *,
        fallback_key: str = "",
    ) -> RestrictedRunSuccess:
        # Duck-typed for injectable test doubles that only implement stdout/stderr/exit_code.
        argv = getattr(result, "argv", None)
        return RestrictedRunSuccess(
            key=str(getattr(result, "key", None) or fallback_key),
            argv=tuple(argv) if argv else tuple(preview_argv),
            exit_code=int(getattr(result, "exit_code", 0) or 0),
            stdout=getattr(result, "stdout", "") or "",
            stderr=getattr(result, "stderr", "") or "",
            duration_ms=int(getattr(result, "duration_ms", 0) or 0),
        )

    @staticmethod
    def _fail(
        kind: AdapterFailureKind,
        key: str,
        message: str,
        *,
        exit_code: Optional[int] = None,
        stdout: str = "",
        stderr: str = "",
        argv: Sequence[str] = (),
    ) -> RestrictedRunFailure:
        # Never log stdout/stderr — they may contain user document content or secrets.
        logger.warning(
            "restricted_runner.fail tool=%s kind=%s message=%s exit=%s argv=%s",
            key,
            kind,
            message[:500],
            exit_code,
            list(argv),
        )
        return RestrictedRunFailure(
            kind=kind,
            key=key,
            message=message[:2000],
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            argv=tuple(argv),
        )


#: Shared restricted runner bound to the process-wide default toolchain runner.
default_restricted_runner = RestrictedRunner()
