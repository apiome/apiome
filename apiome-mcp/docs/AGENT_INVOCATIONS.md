# Agent invocation audit & usage rollups (AGX-3.3)

**Ticket:** AGX-3.3 ([#4539](https://github.com/apiome/apiome/issues/4539)). Schema: apiome-db
`V271__agent_invocations_agx_3_3.sql`. Code: [`apiome_mcp.agent_invocations`](../src/apiome_mcp/agent_invocations.py)
(write path), [`apiome_mcp.agent_usage_sweep`](../src/apiome_mcp/agent_usage_sweep.py) (rollups + retention).

A tenant can answer *which agent called which tool, when, how fast, with what outcome*, while
Apiome keeps none of the request or response bodies by default.

## Tables

| Table | One row per | Holds |
|---|---|---|
| `agent_invocations` | agent `tools/call` | tenant, key, toolset, tool, target (`prod`/`mock`), `invoked_at` (+ UTC `invoked_day`), `latency_ms`, `outcome`, `error_code`, upstream `http_status`, `request_bytes`, `response_bytes`, `sampled` |
| `agent_invocation_samples` | sampled call (opt-in only) | request/response body text, each ≤ 16 KiB, truncation flags. No headers. |
| `agent_invocation_daily` | tenant × UTC day × key × toolset × tool × target | calls by outcome, `errors`, latency p50/p95/p99/max/sum, request/response bytes |
| `agent_invocation_rollup_days` | UTC day | when it was rolled up, and when it became final |

Outcomes: `success`, `upstream_error` (upstream answered with an error or was unreachable),
`validation_failure` (arguments refused before the upstream), `quota_rejected` (AGX-3.2 limit),
`internal_error`. Every non-success row carries a machine `error_code`
(`^[a-z][a-z0-9_.]{0,63}$`, e.g. `upstream_timeout`); a success row never does.

`key_id` and `toolset_id` have no foreign key, so revoking or deleting a key or toolset never rewrites
history. Deleting the tenant deletes everything. Rows are write-once.

## Writing rows (AGX-2.1 call path)

Wrap each `tools/call` in `audit_invocation`. It writes **exactly one** row when the block exits:

```python
access = current_agent_access()
policy = await load_body_capture_policy(pool, access.key.tenant_id, access.key.toolset_id)
async with audit_invocation(pool, access.key, tool_name=name, target=target,
                            request_bytes=len(raw_args.encode()), capture=policy) as audit:
    ...
    audit.attach_bodies(request_body=raw_args, response_body=text)   # kept only if sampled
    audit.succeeded(http_status=200, response_bytes=len(text.encode()))
    # or: audit.failed(InvocationOutcome.UPSTREAM_ERROR, "upstream_http_error", http_status=502)
```

| Block ends with | Recorded as |
|---|---|
| `succeeded(...)` | `success` |
| `failed(outcome, code, ...)` | that outcome and code |
| an exception, `classify(exc)` returns `(outcome, code)` | that outcome and code; the exception propagates |
| an exception, not classified | `internal_error` / `unhandled_exception`; the exception propagates |
| nothing reported, no exception | `internal_error` / `outcome_not_reported` |

Recording never breaks a call. If the INSERT fails, the error is logged
(`agent_invocation_record_failed`) and the call's own result or exception is unchanged.

Calls refused **before** the tool runs (missing/invalid key, unknown or non-permitted tool) are not
invocations. The key may be unknown and the tool name is chosen by the caller.
`apiome_mcp.agent_access` logs them.

## Sampled body capture (opt-in, bounded)

Bodies are captured only when a toolset opts in:

```sql
UPDATE apiome.agent_toolsets
SET body_capture_rate = 0.05, body_capture_until = now() + interval '2 days'
WHERE id = '<toolset>' AND tenant_id = '<tenant>';
```

- `body_capture_rate` is 0..1 and defaults to `0`, which captures nothing. While it is above 0,
  `body_capture_until` is required.
- When written, the window may end at most **7 days** ahead (trigger). Capture stops when the window
  closes.
- The sampling decision is made once per call. Each body is cut to 16 KiB on a character boundary.
- Samples are purged after **7 days**, whatever the tier. They are also deleted with their
  invocation.

There is no API or UI for this setting yet; setting it is an operator action.

## Rollups and retention

The sweep runs every `APIOME_MCP_AGENT_USAGE_SWEEP_INTERVAL_SECONDS` (default 1 h) inside the
server, or once via `apiome-mcp agent-usage sweep`. Each tick runs in one transaction behind
`pg_try_advisory_xact_lock(hashtext('apiome.agent_usage_sweep'))`, so on a multi-instance
deployment only one instance works per tick:

1. `rollup_agent_invocation_days(now, grace)` recomputes every open UTC day from the raw rows
   (idempotent upsert). A day becomes **final** once it ended more than
   `APIOME_MCP_AGENT_USAGE_FINALIZE_GRACE_HOURS` ago (default 6), and a final day is never
   recomputed.
2. `purge_agent_invocations` deletes raw rows that are past the tenant's tier retention **and**
   on a final day. Every pruned row was therefore already counted, and rollups are never touched.
3. `purge_agent_invocation_samples` deletes samples older than 7 days.
4. `purge_agent_invocation_rollups` deletes rollups past the tier's rollup retention.
5. `purge_upstream_credential_uses(APIOME_MCP_AGENT_UPSTREAM_USE_RETENTION_DAYS)` applies the
   AGX-2.2 ledger retention, which V268 left unscheduled.

Each purge deletes at most `APIOME_MCP_AGENT_USAGE_SWEEP_BATCH_SIZE` rows per tick. Whatever is
left goes on the next tick.

### Per-tier retention (`licenses.seats`)

| Tier | `agent_invocation_retention_days` (raw) | `agent_usage_rollup_retention_days` (rollups) |
|---|---|---|
| Free (and unlicensed tenants) | 7 | 90 |
| Paid | 30 | 395 |
| Sponsor | 90 | 730 |

V271 seeds these values fill-if-absent, so an operator's own value is kept. A negative value keeps
rows forever. Raw retention is at least 1 day. A missing or non-numeric key falls back to Free.

## For later tickets

- **AGX-2.1 (#4533)** wraps every `tools/call` in `audit_invocation`
  ([`agent_invocation_proxy`](../src/apiome_mcp/agent_invocation_proxy.py)): `success`,
  `validation_failure` (`invalid_arguments`), `upstream_error` (the reason, e.g. `upstream_timeout`)
  or `internal_error`. The body-capture opt-in is read with the toolset manifest, not a second query.
- **AGX-3.2 (#4538)** counts today's calls per key from `agent_invocations` with V272's
  `agent_key_call_count` (served by `idx_agent_invocations_key_time`). `AgentQuotaMiddleware` refuses calls over
  a limit before the tool runs and writes their `quota_rejected` rows itself, so the AGX-2.1 call
  path audits only the calls it was given. See [`AGENT_QUOTAS.md`](AGENT_QUOTAS.md).
- **AGX-3.4 (#4540)** charts read `agent_invocation_daily`. For today's partial day, the current
  day's rollup is refreshed every tick.
- **AGX-3.5 (#4541)** anomaly detection reads rollups for baselines and raw rows for the recent
  window.
