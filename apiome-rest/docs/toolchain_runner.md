# Polyglot toolchain runner (MFI-5.1)

> **Status:** runner service + tool registry + sample tool — `src/app/toolchain_runner.py`
> **Issue:** [#3750](https://github.com/objectified-project/objectified/issues/3750) ·
> **Epic:** MFI-EPIC-5 (#3720) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

Many authoritative parsers/linters/diff tools the multi-format import roadmap needs are
**not Python** — `buf` (protobuf), `tsp` (TypeSpec), `smithy`, `drafter` (API Blueprint),
AMF (RAML, JVM), the AsyncAPI CLI, graphql-inspector. The toolchain runner is the one
seam every format adapter uses to shell out to one of these **safely and uniformly** and
get **structured JSON** back.

```
 register a tool (key + executable + base args)         run it
 ToolSpec ─▶ registry ──────────────────────────▶ ToolchainRunner.run(key, args)
                                                   │ constrained subprocess (no shell,
                                                   │ sanitized env, per-call timeout)
                                                   ▼
                                              ToolRunResult(exit_code, stdout, stderr,
                                                            parsed_json, duration_ms)
```

## The contract

| Member | Purpose |
|--------|---------|
| `ToolSpec` | how to invoke a tool: `key`, `executable`, `base_args`, `default_timeout_seconds`, `env_override_keys`, `env_passthrough`, `parses_json` |
| `register_tool` / `get_tool` / `available_tools` / `describe_tools` | by-key registry (mirrors the ImportSource registry) |
| `ToolchainRunner.run(key, args, …)` | resolve a registered tool and run it |
| `ToolchainRunner.run_spec(spec, args, …)` | run a `ToolSpec` directly (no registry lookup) |
| `run_tool(...)` | module convenience over the shared `default_runner` |
| `ToolRunResult` | `key`, `argv`, `exit_code`, `stdout`, `stderr`, `parsed_json`, `duration_ms` |

A run is **constrained**: an explicit argv (never a shell), a **sanitized environment**
(only an allow-list of host vars is forwarded — `DATABASE_URL`, JWT secrets, and cloud
credentials are dropped so a third-party CLI never sees the service's secrets), an
optional working directory, and a **per-call timeout** that *kills* the process. Calls are
capped at `APIOME_TOOLCHAIN_MAX_CONCURRENCY` (default 4) simultaneous subprocesses via
an `asyncio.Semaphore`; excess calls queue.

## Structured errors

Every failure mode is a typed `ToolchainError` carrying the tool `key`:

| Error | When |
|-------|------|
| `ToolNotRegisteredError` | the key is not in the registry |
| `ToolNotAvailableError` | the executable is not on `PATH` (the "format unavailable" path for MFI-5.2) |
| `ToolTimeoutError` | the call exceeded its timeout (process killed) |
| `ToolExecutionError` | the tool exited non-zero (carries `exit_code` + captured streams) |
| `ToolOutputError` | `parses_json` but stdout was not valid JSON |

## Registering a tool

```python
from app.toolchain_runner import ToolSpec, register_tool, run_tool

register_tool(ToolSpec(
    key="buf",
    executable="buf",                       # resolved on PATH (or APIOME_BUF_BIN)
    base_args=("build", "--output", "-"),
    env_override_keys=("APIOME_BUF_BIN",),
    default_timeout_seconds=60.0,
))

result = await run_tool("buf", ["proto/api.proto"])
model = result.parsed_json
```

## Built-in sample tool

`sample-echo` (`SAMPLE_ECHO_TOOL_KEY`) is a portable JSON echo run via the current Python
interpreter. It is the acceptance vehicle and the smallest worked example — it lets the
runner be exercised end-to-end (parsed JSON, timeout, non-zero, concurrency) **without
bundling a real external CLI**, which is the next ticket.

## Out of scope (later MFI-EPIC-5 tickets)

- **MFI-5.2 — tool runtime packaging:** ✅ done (#3751). The pinned binaries (buf, tsp,
  smithy, drafter, AMF, asyncapi, rover) are bundled into the runtime image and declared in
  `app.toolchain_packaging`; a missing tool degrades to a "format unavailable" status
  (`probe_tool` / `GET /v1/ops/toolchain`) instead of only surfacing at call time as
  `ToolNotAvailableError`. See [`docs/toolchain_packaging.md`](toolchain_packaging.md).
- **MFI-5.3 — sandbox security & resource limits:** ✅ done (#3752). Every run carries a
  `SandboxPolicy` (`app.toolchain_sandbox`): the subprocess is launched in an isolated network
  namespace (no-network default), its resources are clamped via a `preexec_fn`
  (CPU/memory/file-size/process `setrlimit`), an oversized `stdin` is rejected before spawning,
  and runaway output is killed mid-stream. Network opt-in for live discovery routes through the
  SSRF guard. See [`docs/toolchain_sandbox.md`](toolchain_sandbox.md).
