"""Tests for the polyglot toolchain runner service (MFI-5.1, #3750).

The runner shells out to external CLIs in a constrained subprocess and returns parsed
JSON. To exercise it portably (without bundling buf/tsp/… — that is MFI-5.2), the tests
drive the built-in ``sample-echo`` tool and small ad-hoc :class:`ToolSpec`s that run the
current Python interpreter: a sleeper (timeout), a non-zero exit, and a non-JSON printer.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.toolchain_runner import (
    SAMPLE_ECHO_TOOL_KEY,
    ToolchainRunner,
    ToolExecutionError,
    ToolNotAvailableError,
    ToolNotRegisteredError,
    ToolOutputError,
    ToolSpec,
    ToolTimeoutError,
    available_tools,
    describe_tools,
    get_tool,
    register_tool,
    run_tool,
)


def _py_spec(key: str, code: str, **kw) -> ToolSpec:
    """A ToolSpec that runs ``python -c <code>`` — a portable stand-in for a real CLI."""
    return ToolSpec(key=key, executable=sys.executable, base_args=("-c", code), **kw)


def _runner(max_concurrency: int = 4, default_timeout_seconds: float = 30.0) -> ToolchainRunner:
    return ToolchainRunner(
        max_concurrency=max_concurrency, default_timeout_seconds=default_timeout_seconds
    )


# --- registry ---------------------------------------------------------------


def test_sample_tool_is_registered_and_described():
    assert SAMPLE_ECHO_TOOL_KEY in available_tools()
    spec = get_tool(SAMPLE_ECHO_TOOL_KEY)
    assert spec is not None and spec.parses_json is True

    described = {d.key: d for d in describe_tools()}
    assert SAMPLE_ECHO_TOOL_KEY in described
    assert described[SAMPLE_ECHO_TOOL_KEY].parses_json is True


def test_register_tool_rejects_empty_key_and_executable():
    with pytest.raises(ValueError):
        register_tool(ToolSpec(key="", executable="x"))
    with pytest.raises(ValueError):
        register_tool(ToolSpec(key="x", executable=""))


def test_register_tool_conflicting_spec_raises():
    spec_a = _py_spec("dup-tool", "import sys")
    register_tool(spec_a)
    # Re-registering the identical spec is a no-op.
    register_tool(spec_a)
    # A different spec under the same key is rejected.
    with pytest.raises(ValueError, match="already registered"):
        register_tool(_py_spec("dup-tool", "print('different')"))


# --- happy path: parsed JSON ------------------------------------------------


async def test_runs_sample_tool_returns_parsed_json():
    result = await run_tool(SAMPLE_ECHO_TOOL_KEY, ["alpha", "beta"], stdin="payload")
    assert result.exit_code == 0
    assert result.parsed_json == {
        "tool": "sample-echo",
        "args": ["alpha", "beta"],
        "stdin": "payload",
    }
    assert result.duration_ms >= 0
    assert result.argv[0] == sys.executable


async def test_run_spec_without_registry():
    runner = _runner()
    spec = _py_spec("inline-json", "import json,sys; print(json.dumps({'ok': True}))")
    result = await runner.run_spec(spec)
    assert result.parsed_json == {"ok": True}


async def test_non_json_tool_returns_raw_stdout_when_not_parsing():
    runner = _runner()
    spec = _py_spec("plain-text", "print('just text')", parses_json=False)
    result = await runner.run_spec(spec)
    assert result.parsed_json is None
    assert result.stdout.strip() == "just text"


# --- error handling ---------------------------------------------------------


async def test_unknown_tool_raises_not_registered():
    with pytest.raises(ToolNotRegisteredError) as ei:
        await run_tool("no-such-tool")
    assert ei.value.key == "no-such-tool"


async def test_missing_executable_raises_not_available():
    runner = _runner()
    spec = ToolSpec(key="ghost", executable="definitely-not-a-real-binary-xyz")
    with pytest.raises(ToolNotAvailableError) as ei:
        await runner.run_spec(spec)
    assert ei.value.key == "ghost"


async def test_non_zero_exit_raises_execution_error_with_streams():
    runner = _runner()
    spec = _py_spec(
        "boom",
        "import sys; sys.stderr.write('the failure'); sys.exit(3)",
    )
    with pytest.raises(ToolExecutionError) as ei:
        await runner.run_spec(spec)
    assert ei.value.exit_code == 3
    assert "the failure" in ei.value.stderr


async def test_invalid_json_output_raises_output_error():
    runner = _runner()
    spec = _py_spec("bad-json", "print('not json {')")
    with pytest.raises(ToolOutputError) as ei:
        await runner.run_spec(spec)
    assert ei.value.key == "bad-json"


async def test_timeout_kills_process_and_raises():
    runner = _runner()
    spec = _py_spec("sleeper", "import time; time.sleep(5)")
    with pytest.raises(ToolTimeoutError) as ei:
        await runner.run_spec(spec, timeout=0.2)
    assert ei.value.timeout_seconds == 0.2


# --- environment sanitization ----------------------------------------------


async def test_secrets_are_dropped_from_subprocess_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    runner = _runner()
    spec = _py_spec(
        "env-probe",
        "import json,os; print(json.dumps({'has_db': 'DATABASE_URL' in os.environ}))",
    )
    result = await runner.run_spec(spec)
    assert result.parsed_json == {"has_db": False}


async def test_extra_env_is_forwarded():
    runner = _runner()
    spec = _py_spec(
        "env-extra",
        "import json,os; print(json.dumps({'v': os.environ.get('MY_TOOL_VAR')}))",
    )
    result = await runner.run_spec(spec, extra_env={"MY_TOOL_VAR": "present"})
    assert result.parsed_json == {"v": "present"}


# --- concurrency cap --------------------------------------------------------


async def test_concurrency_is_capped():
    cap = 2
    runner = _runner(max_concurrency=cap)
    # A short sleeper so several calls overlap and contend for the cap.
    spec = _py_spec("overlap", "import time; time.sleep(0.3); print('{}')")

    results = await asyncio.gather(*(runner.run_spec(spec) for _ in range(6)))

    assert all(r.exit_code == 0 for r in results)
    # The semaphore must have kept in-flight subprocesses at or below the cap, and with
    # six overlapping calls it should actually have reached the cap.
    assert runner.peak_active <= cap
    assert runner.peak_active == cap
    # All slots released after completion.
    assert runner.active == 0
