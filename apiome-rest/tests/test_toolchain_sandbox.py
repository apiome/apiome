"""Tests for the toolchain sandbox — MFI-5.3 (#3752).

The sandbox constrains every tool subprocess: no network by default, ``setrlimit`` CPU /
memory / file-size / process clamps, and input/output size caps. As with the MFI-5.1 runner
tests, real CLIs are not needed — the cases drive the current Python interpreter (a portable
stand-in) under a :class:`SandboxPolicy` and assert the constraint *bites*:

* an oversized ``stdin`` is rejected before spawn;
* runaway output is killed mid-stream;
* the CPU and file-size rlimits kill the tool (``SIGXCPU`` / ``SIGXFSZ``);
* the configured rlimits are visible to the child;
* network-isolation enforcement (``strict`` fails closed, ``best_effort`` tolerates) is
  exercised deterministically by faulting the ``unshare`` syscall;
* the platform-admin ops surface reports the active posture.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.toolchain_runner import (
    ToolchainError,
    ToolchainRunner,
    ToolExecutionError,
    ToolInputTooLargeError,
    ToolOutputTooLargeError,
    ToolResourceLimitError,
    ToolSandboxError,
    ToolSpec,
)
from app.toolchain_sandbox import (
    NETWORK_BEST_EFFORT,
    NETWORK_OFF,
    NETWORK_STRICT,
    SandboxPolicy,
    build_preexec_fn,
)

# The rlimit / namespace clamps are POSIX-only; the behavioral cases assume a POSIX host
# (CI is Linux). The pure-policy cases below run everywhere.
_POSIX = os.name == "posix"


def _py_spec(key: str, code: str, **kw) -> ToolSpec:
    """A ToolSpec that runs ``python -c <code>`` — a portable stand-in for a real CLI."""
    return ToolSpec(key=key, executable=sys.executable, base_args=("-c", code), **kw)


def _runner(policy: SandboxPolicy, default_timeout_seconds: float = 15.0) -> ToolchainRunner:
    return ToolchainRunner(
        max_concurrency=4, default_timeout_seconds=default_timeout_seconds, default_policy=policy
    )


def _unprivileged_userns_net_supported() -> bool:
    """True when this host lets an unprivileged process unshare a network namespace.

    Probed in a throwaway forked child so the test process itself is never moved into a new
    namespace. Used only to decide which side of the best-effort branch to assert — the
    enforcement *logic* is covered deterministically by the fault-injection cases.
    """
    pid = os.fork()
    if pid == 0:  # child
        try:
            import ctypes

            libc = ctypes.CDLL(None, use_errno=True)
            rc = libc.unshare(0x10000000 | 0x40000000)  # CLONE_NEWUSER | CLONE_NEWNET
            os._exit(0 if rc == 0 else 1)
        except Exception:  # noqa: BLE001 - any failure means "not supported"
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status) == 0


# ===========================================================================
# Policy construction & helpers (cross-platform)
# ===========================================================================


def test_from_settings_is_locked_down_by_default():
    policy = SandboxPolicy.from_settings()
    assert policy.no_network is True
    assert policy.network_enforcement == NETWORK_BEST_EFFORT
    assert policy.isolates_network is True
    # The cross-platform caps are configured out of the box.
    assert policy.max_input_bytes and policy.max_input_bytes > 0
    assert policy.max_output_bytes and policy.max_output_bytes > 0
    # Memory/CPU/process clamps are opt-in (None) so JVM tools and shared hosts are not broken.
    assert policy.memory_bytes is None
    assert policy.cpu_seconds is None
    assert policy.max_processes is None


def test_from_settings_falls_back_on_unknown_enforcement(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "toolchain_network_enforcement", "banana")
    policy = SandboxPolicy.from_settings()
    assert policy.network_enforcement == NETWORK_BEST_EFFORT


def test_disabled_policy_isolates_nothing():
    policy = SandboxPolicy.disabled()
    assert policy.no_network is False
    assert policy.isolates_network is False
    assert policy.network_enforcement == NETWORK_OFF


def test_for_live_discovery_lifts_network_keeps_clamps():
    base = SandboxPolicy(no_network=True, cpu_seconds=10.0, max_output_bytes=1234)
    live = base.for_live_discovery()
    assert live.no_network is False
    assert live.isolates_network is False  # caller routes fetches through the SSRF guard
    assert live.cpu_seconds == 10.0
    assert live.max_output_bytes == 1234


def test_describe_exposes_the_posture():
    described = SandboxPolicy.from_settings().describe()
    for field in (
        "no_network",
        "network_enforcement",
        "max_input_bytes",
        "max_output_bytes",
        "file_size_bytes",
        "open_files",
        "posix_enforcement",
    ):
        assert field in described


def test_build_preexec_fn_none_when_nothing_to_enforce():
    # Disabled policy: no network isolation, no rlimits, core dumps allowed → nothing to do.
    policy = SandboxPolicy(
        no_network=False,
        network_enforcement=NETWORK_OFF,
        allow_core_dumps=True,
    )
    assert build_preexec_fn(policy) is None


@pytest.mark.skipif(not _POSIX, reason="rlimit/namespace clamps are POSIX-only")
def test_build_preexec_fn_callable_when_clamping():
    policy = SandboxPolicy(no_network=True, cpu_seconds=5.0)
    assert callable(build_preexec_fn(policy))


# ===========================================================================
# Input / output size caps (cross-platform behaviour)
# ===========================================================================


async def test_oversized_input_is_rejected_before_spawn():
    policy = SandboxPolicy(no_network=False, network_enforcement=NETWORK_OFF, max_input_bytes=16)
    runner = _runner(policy)
    spec = _py_spec("echo-in", "import sys; sys.stdin.read(); print('{}')")
    with pytest.raises(ToolInputTooLargeError) as ei:
        await runner.run_spec(spec, stdin="x" * 17)
    assert ei.value.size == 17
    assert ei.value.limit == 16
    # The tool must never have run.
    assert runner.peak_active == 0


async def test_input_at_the_limit_is_allowed():
    policy = SandboxPolicy(no_network=False, network_enforcement=NETWORK_OFF, max_input_bytes=16)
    runner = _runner(policy)
    spec = _py_spec(
        "echo-len",
        "import json,sys; print(json.dumps({'n': len(sys.stdin.read())}))",
    )
    result = await runner.run_spec(spec, stdin="x" * 16)
    assert result.parsed_json == {"n": 16}


async def test_runaway_output_is_killed_and_raises():
    policy = SandboxPolicy(
        no_network=False, network_enforcement=NETWORK_OFF, max_output_bytes=4096
    )
    runner = _runner(policy)
    # Emit far more than the cap; the runner must stop reading and kill the process.
    spec = _py_spec(
        "flood",
        "import sys\nfor _ in range(10000): sys.stdout.write('x'*1000)\n",
        parses_json=False,
    )
    with pytest.raises(ToolOutputTooLargeError) as ei:
        await runner.run_spec(spec)
    assert ei.value.limit == 4096
    assert runner.active == 0


async def test_output_under_the_cap_is_returned():
    policy = SandboxPolicy(
        no_network=False, network_enforcement=NETWORK_OFF, max_output_bytes=1_000_000
    )
    runner = _runner(policy)
    spec = _py_spec("small", "import json; print(json.dumps({'ok': True}))")
    result = await runner.run_spec(spec)
    assert result.parsed_json == {"ok": True}


# ===========================================================================
# Resource limits (POSIX: setrlimit enforced by the kernel)
# ===========================================================================


@pytest.mark.skipif(not _POSIX, reason="setrlimit is POSIX-only")
async def test_configured_rlimits_are_visible_to_the_child():
    policy = SandboxPolicy(
        no_network=False,
        network_enforcement=NETWORK_OFF,
        cpu_seconds=5.0,
        memory_bytes=1_073_741_824,  # 1 GiB — generous enough for the interpreter to start
        file_size_bytes=1_048_576,
        open_files=128,
        allow_core_dumps=False,
    )
    runner = _runner(policy)
    spec = _py_spec(
        "limits",
        "import json,resource as r;"
        "print(json.dumps({"
        "'cpu': r.getrlimit(r.RLIMIT_CPU)[0],"
        "'as': r.getrlimit(r.RLIMIT_AS)[0],"
        "'fsize': r.getrlimit(r.RLIMIT_FSIZE)[0],"
        "'nofile': r.getrlimit(r.RLIMIT_NOFILE)[0],"
        "'core': r.getrlimit(r.RLIMIT_CORE)[0]}))",
    )
    result = await runner.run_spec(spec)
    assert result.parsed_json == {
        "cpu": 5,
        "as": 1_073_741_824,
        "fsize": 1_048_576,
        "nofile": 128,
        "core": 0,
    }


@pytest.mark.skipif(not _POSIX, reason="RLIMIT_CPU is POSIX-only")
async def test_cpu_limit_kills_a_runaway_tool():
    policy = SandboxPolicy(no_network=False, network_enforcement=NETWORK_OFF, cpu_seconds=1.0)
    # Wall-clock timeout well above the CPU cap so the *CPU* limit is what fires.
    runner = _runner(policy, default_timeout_seconds=30.0)
    spec = _py_spec("spin", "x=0\nwhile True:\n    x+=1\n")
    with pytest.raises(ToolResourceLimitError) as ei:
        await runner.run_spec(spec)
    assert ei.value.signal_name in ("SIGXCPU", "SIGKILL")


@pytest.mark.skipif(not _POSIX, reason="RLIMIT_FSIZE is POSIX-only")
async def test_file_size_limit_caps_a_disk_bomb(tmp_path):
    # RLIMIT_FSIZE bounds any single file the tool writes. Depending on the kernel/glibc the
    # breach either *kills* the tool with SIGXFSZ (-> ToolResourceLimitError) or fails the write
    # with EFBIG so the tool exits non-zero (-> ToolExecutionError). Either way the cap must hold:
    # the run errors and the file on disk never grows past the limit.
    limit = 65536
    policy = SandboxPolicy(
        no_network=False, network_enforcement=NETWORK_OFF, file_size_bytes=limit
    )
    runner = _runner(policy)
    spec = _py_spec(
        "diskbomb",
        "f=open('out.bin','wb'); f.write(b'x'*(4*1024*1024)); f.flush()",
        parses_json=False,
    )
    with pytest.raises(ToolchainError) as ei:
        await runner.run_spec(spec, cwd=str(tmp_path))
    assert isinstance(ei.value, (ToolResourceLimitError, ToolExecutionError))
    out = tmp_path / "out.bin"
    assert (not out.exists()) or out.stat().st_size <= limit


# ===========================================================================
# Network isolation enforcement
# ===========================================================================


@pytest.mark.skipif(not _POSIX, reason="network namespaces are Linux-only")
async def test_strict_network_fails_closed_when_isolation_unavailable():
    # Fault-inject: make the unshare syscall fail. In strict mode the runner must refuse to
    # run the tool rather than expose it to the network. Patching the module global means the
    # forked child (which looks the symbol up at call time) inherits the fault deterministically.
    policy = SandboxPolicy(no_network=True, network_enforcement=NETWORK_STRICT)
    runner = _runner(policy)
    spec = _py_spec("net", "print('{}')")
    with patch(
        "app.toolchain_sandbox._unshare_network",
        side_effect=OSError(1, "operation not permitted"),
    ):
        with pytest.raises(ToolSandboxError) as ei:
            await runner.run_spec(spec)
    assert ei.value.key == "net"


@pytest.mark.skipif(not _POSIX, reason="network namespaces are Linux-only")
async def test_best_effort_network_tolerates_unavailable_isolation():
    # Same fault, but best-effort: the tool still runs (isolation is skipped, logged).
    policy = SandboxPolicy(no_network=True, network_enforcement=NETWORK_BEST_EFFORT)
    runner = _runner(policy)
    spec = _py_spec("net-ok", "import json; print(json.dumps({'ran': True}))")
    with patch(
        "app.toolchain_sandbox._unshare_network",
        side_effect=OSError(1, "operation not permitted"),
    ):
        result = await runner.run_spec(spec)
    assert result.parsed_json == {"ran": True}


@pytest.mark.skipif(not _POSIX, reason="network namespaces are Linux-only")
async def test_no_network_actually_isolates_the_namespace_when_supported():
    # When the kernel allows unprivileged userns, the child runs in a *different* network
    # namespace than the parent (real isolation). When it does not, best-effort leaves the
    # child in the parent namespace. Either way the run succeeds — both sides are asserted so
    # the test is meaningful where supported and never skips.
    parent_ns = os.readlink("/proc/self/ns/net")
    policy = SandboxPolicy(no_network=True, network_enforcement=NETWORK_BEST_EFFORT)
    runner = _runner(policy)
    spec = _py_spec(
        "ns",
        "import os; print(os.readlink('/proc/self/ns/net'))",
        parses_json=False,
    )
    result = await runner.run_spec(spec)
    child_ns = result.stdout.strip()
    assert child_ns.startswith("net:[")
    if _unprivileged_userns_net_supported():
        assert child_ns != parent_ns
    else:  # pragma: no cover - exercised only on hosts without unprivileged userns
        assert child_ns == parent_ns


# ===========================================================================
# Regression: the default sandbox does not break a normal run
# ===========================================================================


async def test_default_policy_still_runs_a_normal_tool():
    # The shared default policy (no-network best-effort + caps) must not break a benign tool.
    runner = ToolchainRunner(max_concurrency=2, default_timeout_seconds=15.0)
    spec = _py_spec("benign", "import json,sys; print(json.dumps({'args': sys.argv[1:]}))")
    result = await runner.run_spec(spec, ["a", "b"])
    assert result.parsed_json == {"args": ["a", "b"]}


# ===========================================================================
# Ops surface — the sandbox posture is reported alongside tool availability
# ===========================================================================

client = TestClient(app)

_AUTH = {
    "authenticated": True,
    "tenant_slug": "acme",
    "user_id": "11111111-1111-1111-1111-111111111111",
    "user_email": "ops@acme.io",
}


@pytest.fixture
def _auth_override():
    from app.auth import validate_authentication

    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_ops_toolchain_reports_sandbox_posture(_auth_override):
    with patch("app.ops_routes.db") as mdb:
        mdb.is_platform_admin.return_value = True
        r = client.get("/v1/ops/toolchain")
    assert r.status_code == 200
    body = r.json()
    assert "sandbox" in body
    sandbox = body["sandbox"]
    assert sandbox["no_network"] is True
    assert sandbox["network_enforcement"] in ("best_effort", "strict", "off")
    assert sandbox["posix_enforcement"] == (os.name == "posix")
