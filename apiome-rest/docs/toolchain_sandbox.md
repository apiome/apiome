# Toolchain sandbox security & resource limits (MFI-5.3)

> **Status:** sandbox policy + runner integration — `src/app/toolchain_sandbox.py`
> **Issue:** [#3752](https://github.com/objectified-project/objectified/issues/3752) ·
> **Epic:** MFI-EPIC-5 (#3720) · **Roadmap:** `docs/ROADMAP_MULTI_FORMAT_IMPORT.md`

The MFI-5.1 [toolchain runner](toolchain_runner.md) shells out to third-party parser /
linter / diff CLIs (`buf`, `tsp`, `smithy`, …) on **user-supplied input**. That is a
security surface — a hostile document can attempt SSRF (a tool that fetches a `$ref` URL),
arbitrary code execution, or resource exhaustion (a zip-bomb spec that explodes to gigabytes
of output, a tool that spins forever). MFI-5.1 already drops ambient secrets from the child
environment and never uses a shell; MFI-5.3 adds the **OS-level clamps**.

Every run carries a `SandboxPolicy`. The shared runner builds its `default_policy` from
settings (so a deployment tunes it via `APIOME_TOOLCHAIN_*` without code changes), and a
caller may pass its own policy per call.

```
ToolchainRunner.run(key, args, policy=…)        SandboxPolicy
   │                                              ├─ no_network / network_enforcement
   ▼                                              ├─ cpu_seconds / memory_bytes / file_size_bytes
 reject oversized stdin  ◀── max_input_bytes      ├─ max_processes / open_files / core dumps
   │                                              └─ max_input_bytes / max_output_bytes
 spawn (preexec_fn: setrlimit + unshare netns)
   │
 drain stdout/stderr, capped ◀── max_output_bytes (kill + raise if blown)
   ▼
 ToolRunResult  /  ToolInputTooLargeError | ToolOutputTooLargeError |
                   ToolResourceLimitError | ToolSandboxError
```

## What the sandbox enforces

| Control | Mechanism | Default |
|---------|-----------|---------|
| **No network** | child launched in a fresh Linux network namespace (`unshare(CLONE_NEWUSER\|CLONE_NEWNET)`) — only a down loopback, no route off-box | **on** (`best_effort`) |
| **Input size cap** | oversized `stdin` rejected *before* the tool is spawned | 32 MiB |
| **Output size cap** | combined stdout+stderr capped; the tool is killed mid-stream if it floods | 64 MiB |
| **File-size cap** | `RLIMIT_FSIZE` — any single file the tool writes (`SIGXFSZ` on breach) | 512 MiB |
| **Open files** | `RLIMIT_NOFILE` | 1024 |
| **No core dumps** | `RLIMIT_CORE = 0` | on |
| **CPU cap** | `RLIMIT_CPU` CPU-seconds (`SIGXCPU` on breach) | off (wall-clock timeout is the time bound) |
| **Memory cap** | `RLIMIT_AS` address space | off (an AS cap breaks JVM tools — opt in) |
| **Process cap** | `RLIMIT_NPROC` fork-bomb guard | off (per-UID — opt in where the runtime is isolated) |

The `setrlimit` clamps and the network namespace are applied in a `preexec_fn` that runs in
the forked child **after fork, before exec**. The input/output caps are enforced in the
runner itself (cross-platform). On a non-POSIX host the rlimit/namespace clamps are skipped
(`build_preexec_fn` returns `None`) and only the input/output caps apply.

## Network enforcement modes

`network_enforcement` decides how hard the runner insists on isolation when `no_network` is
set:

* **`best_effort`** (default) — isolate when the kernel allows it (unprivileged user
  namespaces enabled), otherwise log and run the tool anyway.
* **`strict`** — *fail closed*: if the network cannot be isolated, refuse to run the tool
  (`ToolSandboxError`). Use this where running a tool with network access is unacceptable.
* **`off`** — do not isolate (only meaningful together with `no_network=False`).

## Opting into the network for live discovery

A tool that genuinely needs the network — gRPC reflection, a schema-registry crawl — opts
out of isolation:

```python
from app.toolchain_sandbox import SandboxPolicy

policy = SandboxPolicy.from_settings().for_live_discovery()  # network allowed, clamps kept
result = await runner.run("buf", ["..."], policy=policy)
```

When you lift the no-network default, the **caller** becomes responsible for routing the
tool's outbound fetches through the SSRF guard (`app.ssrf_guard`, EPIC-16.6 / #3612), which
rejects loopback / RFC1918 / link-local (incl. the `169.254.169.254` metadata IP) targets.
The runner's no-network default is the belt; the SSRF guard is the braces.

## Structured errors

| Error | When |
|-------|------|
| `ToolInputTooLargeError` | `stdin` exceeded `max_input_bytes` (rejected before spawn) |
| `ToolOutputTooLargeError` | combined output exceeded `max_output_bytes` (tool killed mid-stream) |
| `ToolResourceLimitError` | the tool was killed by the kernel for a CPU (`SIGXCPU`) or file-size (`SIGXFSZ`) cap |
| `ToolSandboxError` | `strict` enforcement and the network could not be isolated (fail closed) |

These join the MFI-5.1 errors (`ToolNotRegisteredError`, `ToolNotAvailableError`,
`ToolTimeoutError`, `ToolExecutionError`, `ToolOutputError`).

## Settings

| Setting | Env | Default |
|---------|-----|---------|
| `toolchain_no_network` | `APIOME_TOOLCHAIN_NO_NETWORK` | `true` |
| `toolchain_network_enforcement` | `APIOME_TOOLCHAIN_NETWORK_ENFORCEMENT` | `best_effort` |
| `toolchain_max_input_bytes` | `APIOME_TOOLCHAIN_MAX_INPUT_BYTES` | `33554432` (32 MiB) |
| `toolchain_max_output_bytes` | `APIOME_TOOLCHAIN_MAX_OUTPUT_BYTES` | `67108864` (64 MiB) |
| `toolchain_file_size_bytes` | `APIOME_TOOLCHAIN_FILE_SIZE_BYTES` | `536870912` (512 MiB) |
| `toolchain_open_files` | `APIOME_TOOLCHAIN_OPEN_FILES` | `1024` |
| `toolchain_cpu_seconds` | `APIOME_TOOLCHAIN_CPU_SECONDS` | unset (off) |
| `toolchain_memory_bytes` | `APIOME_TOOLCHAIN_MEMORY_BYTES` | unset (off) |
| `toolchain_max_processes` | `APIOME_TOOLCHAIN_MAX_PROCESSES` | unset (off) |

The active posture is surfaced (platform-admin) at `GET /v1/ops/toolchain` in the `sandbox`
block alongside per-tool availability.

## Scope note: read-only filesystem

Full read-only-root / mount isolation requires a mount namespace or a container hardened at
deploy time (the runtime image), which is out of scope for an in-process `preexec_fn`. What
the sandbox enforces in-process is the network-namespace isolation, the `RLIMIT_FSIZE`
file-size cap (a zip-bomb-to-disk guard), no core dumps, and no inherited writable handles
beyond the pipes. Pair it with a read-only container root and a writable scratch `tmpfs` for
defence in depth.
