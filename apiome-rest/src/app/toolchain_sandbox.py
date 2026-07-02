"""Sandbox security & resource limits for the toolchain runner — MFI-5.3 (#3752).

MFI-5.1 (:mod:`app.toolchain_runner`) runs third-party parser/linter/diff CLIs
(``buf``, ``tsp``, ``smithy``, …) on **user-supplied input**. That is a security surface:
a hostile document can try SSRF (a tool that fetches a ``$ref`` URL), arbitrary code exec,
or resource exhaustion — a zip-bomb spec that explodes to gigabytes of output, or a tool
that spins forever burning CPU. MFI-5.1 already drops ambient secrets from the child
environment and never uses a shell; this module adds the **OS-level clamps** MFI-5.3 owns.

A :class:`SandboxPolicy` describes the constraints applied to every tool subprocess:

* **no network by default** — the child is launched in a fresh Linux *network namespace*
  (via ``unshare(CLONE_NEWUSER | CLONE_NEWNET)``) so it has only a down loopback and cannot
  reach the cloud metadata IP, internal services, or the public internet. Enforcement is
  configurable: ``best_effort`` (the default — isolate when the kernel allows it, otherwise
  log and continue) or ``strict`` (refuse to run the tool if the network cannot be isolated,
  i.e. *fail closed*). A tool that genuinely needs the network for live discovery (gRPC
  reflection, registry crawl) opts in with :meth:`SandboxPolicy.for_live_discovery`, and the
  *caller* is then responsible for routing its fetches through the SSRF guard
  (:mod:`app.ssrf_guard`, EPIC-16.6 / #3612) — the runner's no-network default is the
  belt-and-braces opposite stance.
* **resource limits** — POSIX ``setrlimit`` clamps applied in a ``preexec_fn`` after fork,
  before exec: CPU seconds, address space (memory), output file size, max child processes
  (fork-bomb guard), open files, and a zeroed core-dump limit. Limits the kernel enforces:
  exceeding the CPU cap kills the tool with ``SIGXCPU``; exceeding the file-size cap kills
  it with ``SIGXFSZ`` — both surfaced as :class:`~app.toolchain_runner.ToolResourceLimitError`.
* **input/output size caps** — enforced in the runner itself (not the kernel): an oversized
  ``stdin`` is rejected *before* the tool is spawned, and a tool whose combined stdout+stderr
  exceeds the output cap is killed mid-stream so a zip-bomb can never blow the service's
  memory. These live in the policy here; the runner reads them.

Platform note: the ``setrlimit`` and namespace mechanisms are **POSIX/Linux only**. On a
non-POSIX host (or when the ``resource`` module is unavailable) :func:`build_preexec_fn`
returns ``None`` and only the cross-platform input/output caps apply. Full read-only-root FS
isolation needs a mount namespace / container at deploy time (the runtime image), which is
out of scope for an in-process ``preexec_fn``; what we enforce here — no network, a file-size
cap, no inherited writable handles beyond the pipes — is the in-process half.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from .config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "SandboxPolicy",
    "SandboxSetupError",
    "build_preexec_fn",
    "NETWORK_OFF",
    "NETWORK_BEST_EFFORT",
    "NETWORK_STRICT",
    "NETWORK_ENFORCEMENT_MODES",
]


# Network-enforcement modes (how hard we insist on isolating the child's network).
NETWORK_OFF = "off"  # do not isolate; the child keeps the host's network (only with no_network=False)
NETWORK_BEST_EFFORT = "best_effort"  # isolate when the kernel allows it, else log + continue
NETWORK_STRICT = "strict"  # refuse to run the tool if the network cannot be isolated (fail closed)
NETWORK_ENFORCEMENT_MODES = (NETWORK_OFF, NETWORK_BEST_EFFORT, NETWORK_STRICT)

# Linux ``clone``/``unshare`` flags. A single unshare with both flags creates a user
# namespace (so an unprivileged process is permitted to create the network namespace) and a
# fresh network namespace with only a *down* loopback — no route to anything off-box.
_CLONE_NEWUSER = 0x10000000
_CLONE_NEWNET = 0x40000000


class SandboxSetupError(Exception):
    """The constrained child could not be set up (e.g. strict network isolation failed).

    Raised inside the ``preexec_fn`` (post-fork). CPython transfers a preexec failure to the
    parent as a :class:`subprocess.SubprocessError`, which the runner maps to a
    :class:`~app.toolchain_runner.ToolSandboxError`.
    """


@dataclass(frozen=True)
class SandboxPolicy:
    """The OS-level constraints applied to one tool subprocess.

    A field set to ``None`` means *that* clamp is not applied (the kernel default stands).
    The cross-platform input/output caps are read by the runner; the ``setrlimit`` and
    network fields are realised by :func:`build_preexec_fn` in the forked child.

    Attributes:
        no_network: When ``True`` (default), launch the child in an isolated network
            namespace so it cannot reach any network. ``False`` opts the tool into the host
            network (live discovery) — see :meth:`for_live_discovery`.
        network_enforcement: How hard to insist on isolation when ``no_network`` is set —
            ``"best_effort"`` (default) or ``"strict"`` (fail closed). ``"off"`` disables
            isolation entirely (only meaningful with ``no_network=False``).
        cpu_seconds: ``RLIMIT_CPU`` ceiling (CPU-seconds, not wall-clock). ``None`` → no CPU
            clamp; the runner's wall-clock timeout is the primary time bound.
        memory_bytes: ``RLIMIT_AS`` address-space ceiling. ``None`` by default — an
            address-space cap can break JVM tools (``smithy``/``amf`` reserve large virtual
            space), so memory limiting is opt-in per deployment.
        file_size_bytes: ``RLIMIT_FSIZE`` ceiling on any single file the tool writes (a
            zip-bomb-to-disk guard). Exceeding it kills the tool with ``SIGXFSZ``.
        max_processes: ``RLIMIT_NPROC`` ceiling (fork-bomb guard). ``None`` by default —
            ``RLIMIT_NPROC`` is per-UID, so a low value can interfere with co-tenant
            processes on a shared host; opt in where the runtime is isolated.
        open_files: ``RLIMIT_NOFILE`` ceiling on open file descriptors.
        allow_core_dumps: When ``False`` (default) ``RLIMIT_CORE`` is zeroed so a crashing
            tool cannot litter the disk with core files.
        max_input_bytes: Reject (before spawning) a ``stdin`` payload larger than this.
        max_output_bytes: Kill the tool and raise if its combined stdout+stderr exceeds this.
    """

    no_network: bool = True
    network_enforcement: str = NETWORK_BEST_EFFORT
    cpu_seconds: Optional[float] = None
    memory_bytes: Optional[int] = None
    file_size_bytes: Optional[int] = None
    max_processes: Optional[int] = None
    open_files: Optional[int] = None
    allow_core_dumps: bool = False
    max_input_bytes: Optional[int] = None
    max_output_bytes: Optional[int] = None

    @classmethod
    def from_settings(cls) -> "SandboxPolicy":
        """Build the default policy from :data:`app.config.settings`.

        This backs the shared ``default_runner`` so a deployment tunes the sandbox via
        ``APIOME_TOOLCHAIN_*`` environment variables without code changes.
        """
        mode = str(settings.toolchain_network_enforcement).strip().lower()
        if mode not in NETWORK_ENFORCEMENT_MODES:
            logger.warning(
                "unknown toolchain_network_enforcement %r; falling back to %r",
                settings.toolchain_network_enforcement,
                NETWORK_BEST_EFFORT,
            )
            mode = NETWORK_BEST_EFFORT
        return cls(
            no_network=bool(settings.toolchain_no_network),
            network_enforcement=mode,
            cpu_seconds=settings.toolchain_cpu_seconds,
            memory_bytes=settings.toolchain_memory_bytes,
            file_size_bytes=settings.toolchain_file_size_bytes,
            max_processes=settings.toolchain_max_processes,
            open_files=settings.toolchain_open_files,
            allow_core_dumps=False,
            max_input_bytes=settings.toolchain_max_input_bytes,
            max_output_bytes=settings.toolchain_max_output_bytes,
        )

    @classmethod
    def disabled(cls) -> "SandboxPolicy":
        """A no-op policy: no network isolation, no rlimits, no input/output caps.

        For call sites (or tests) that must run a tool entirely unconstrained.
        """
        return cls(
            no_network=False,
            network_enforcement=NETWORK_OFF,
            allow_core_dumps=True,
        )

    def for_live_discovery(self) -> "SandboxPolicy":
        """Return a copy that opts into the host network for explicit live discovery.

        Keeps every resource/output clamp but lifts network isolation (gRPC reflection,
        schema-registry crawl). The **caller** must route the tool's outbound fetches through
        the SSRF guard (:mod:`app.ssrf_guard`) — lifting the no-network default here removes
        the runner's belt; the SSRF guard is the braces.
        """
        return SandboxPolicy(
            no_network=False,
            network_enforcement=NETWORK_OFF,
            cpu_seconds=self.cpu_seconds,
            memory_bytes=self.memory_bytes,
            file_size_bytes=self.file_size_bytes,
            max_processes=self.max_processes,
            open_files=self.open_files,
            allow_core_dumps=self.allow_core_dumps,
            max_input_bytes=self.max_input_bytes,
            max_output_bytes=self.max_output_bytes,
        )

    @property
    def isolates_network(self) -> bool:
        """True when this policy actively isolates the child's network namespace."""
        return self.no_network and self.network_enforcement != NETWORK_OFF

    def describe(self) -> Dict[str, object]:
        """A JSON-serializable summary of the policy (for the ops surface)."""
        return {
            "no_network": self.no_network,
            "network_enforcement": self.network_enforcement,
            "cpu_seconds": self.cpu_seconds,
            "memory_bytes": self.memory_bytes,
            "file_size_bytes": self.file_size_bytes,
            "max_processes": self.max_processes,
            "open_files": self.open_files,
            "core_dumps": self.allow_core_dumps,
            "max_input_bytes": self.max_input_bytes,
            "max_output_bytes": self.max_output_bytes,
            "posix_enforcement": os.name == "posix",
        }


def _rlimits_for(policy: SandboxPolicy) -> Dict[int, Tuple[int, int]]:
    """Map a policy to the concrete ``resource.RLIMIT_* → (soft, hard)`` tuples to apply.

    Only resources the policy actually clamps are included. Unknown/unsupported resource
    constants on the running kernel are skipped (``getattr`` guarded). Returns an empty dict
    when the ``resource`` module is unavailable (non-POSIX).
    """
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX only
        return {}

    limits: Dict[int, Tuple[int, int]] = {}
    if policy.cpu_seconds is not None:
        # RLIMIT_CPU is whole seconds; round up so a fractional cap never under-shoots to 0.
        # Soft < hard so the kernel sends SIGXCPU (terminate) a CPU-second before it escalates
        # to an unconditional SIGKILL at the hard limit — giving the clean, attributable kill.
        secs = max(1, int(math.ceil(policy.cpu_seconds)))
        limits[resource.RLIMIT_CPU] = (secs, secs + 1)
    if policy.memory_bytes is not None:
        limits[resource.RLIMIT_AS] = (policy.memory_bytes, policy.memory_bytes)
    if policy.file_size_bytes is not None:
        limits[resource.RLIMIT_FSIZE] = (policy.file_size_bytes, policy.file_size_bytes)
    if policy.max_processes is not None and hasattr(resource, "RLIMIT_NPROC"):
        limits[resource.RLIMIT_NPROC] = (policy.max_processes, policy.max_processes)
    if policy.open_files is not None:
        limits[resource.RLIMIT_NOFILE] = (policy.open_files, policy.open_files)
    if not policy.allow_core_dumps:
        limits[resource.RLIMIT_CORE] = (0, 0)
    return limits


def _reset_resource_signals() -> None:
    """Reset the resource-limit signals to their default (terminate) disposition.

    Runs in the forked child before exec. Resets ``SIGXCPU`` and ``SIGXFSZ`` (and ``SIGPIPE``)
    to ``SIG_DFL`` so a CPU / file-size rlimit breach reliably *kills* the tool with that
    signal — independent of any ``SIG_IGN`` the parent process happened to install (uv, pytest,
    and many servers ignore some of these, and dispositions survive ``exec``). Best-effort:
    failures (e.g. a platform lacking a given signal) are swallowed.
    """
    import signal as _signal

    for name in ("SIGXCPU", "SIGXFSZ", "SIGPIPE"):
        sig = getattr(_signal, name, None)
        if sig is None:
            continue
        try:
            _signal.signal(sig, _signal.SIG_DFL)
        except (OSError, ValueError):
            # ValueError: not the main thread (rare under our event loop); OSError: unsupported.
            pass


def _unshare_network() -> None:
    """Move the calling (forked, pre-exec) process into a fresh, isolated network namespace.

    Uses ``unshare(CLONE_NEWUSER | CLONE_NEWNET)`` so an unprivileged process may create the
    network namespace. The new namespace has only a down loopback — no route off-box.

    Raises:
        OSError: if ``unshare`` is unavailable or the kernel refuses (e.g. unprivileged user
            namespaces disabled). The caller decides whether that is fatal (strict) or
            tolerable (best-effort).
    """
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, "unshare"):
        raise OSError("unshare() is not available on this platform")
    ctypes.set_errno(0)
    if libc.unshare(_CLONE_NEWUSER | _CLONE_NEWNET) != 0:
        errno = ctypes.get_errno()
        raise OSError(
            errno,
            f"unshare(CLONE_NEWUSER|CLONE_NEWNET) failed: {os.strerror(errno)}",
        )


def build_preexec_fn(policy: SandboxPolicy) -> Optional[Callable[[], None]]:
    """Build the ``preexec_fn`` that realises ``policy`` in a tool subprocess.

    The returned callable runs in the forked child **after fork, before exec** (single-
    threaded at that point, so the namespace/rlimit syscalls are safe). It applies the
    ``setrlimit`` clamps and, when the policy isolates the network, unshares into a fresh
    network namespace.

    Returns:
        The ``preexec_fn`` callable, or ``None`` when there is nothing to enforce or the host
        is non-POSIX (in which case the runner spawns without a ``preexec_fn`` and only the
        input/output caps apply).
    """
    if os.name != "posix":
        return None

    rlimits = _rlimits_for(policy)
    isolate_network = policy.isolates_network
    if not rlimits and not isolate_network:
        return None

    enforcement = policy.network_enforcement

    def _preexec() -> None:
        # The resource-limit signals must use the kernel's default (terminate) disposition: an
        # ambient SIG_IGN inherited from the parent (uv/pytest/servers commonly ignore SIGXFSZ)
        # would otherwise turn a CPU/file-size breach into a survivable EFBIG/escalated SIGKILL
        # instead of the clean SIGXCPU/SIGXFSZ kill the runner reports as a resource-limit error.
        _reset_resource_signals()
        # Resource clamps next so they bound even the namespace setup that follows.
        if rlimits:
            import resource

            for res, (soft, hard) in rlimits.items():
                try:
                    resource.setrlimit(res, (soft, hard))
                except (ValueError, OSError):
                    # A limit this kernel does not support must not abort the whole spawn;
                    # the remaining clamps still apply. (Cannot log usefully post-fork.)
                    pass
        if isolate_network:
            try:
                _unshare_network()
            except OSError as exc:
                if enforcement == NETWORK_STRICT:
                    # Fail closed: refuse to run the tool with network access we cannot remove.
                    raise SandboxSetupError(
                        f"could not isolate tool network namespace: {exc}"
                    ) from exc
                # best_effort: the kernel will not let us isolate; run anyway (logged in parent).

    return _preexec
