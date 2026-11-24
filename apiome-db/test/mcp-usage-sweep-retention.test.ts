/**
 * DBP-1.23 (#7206), migration V429: the MCP usage sweep's batched retention, incremental rollups and
 * audit retention.
 *
 * Two layers:
 *   1. Structural promises of the migration (order, indexes, signatures, idempotent statements).
 *   2. Behaviour, on a migrated database:
 *      - the rollups the new functions write — one day per call, incrementally — equal, value for
 *        value, what V271's functions write for the same calls and ticks (V271's bodies are loaded
 *        from its file into pg_temp as the reference);
 *      - the purge deletes exactly the rows V271's purge deletes, in batches;
 *      - a tick with nothing to do reads index ranges only: no sequential scan of the swept tables
 *        and a handful of index tuples;
 *      - the credential-use, access-audit and capability-denial purges are batched and keep rows
 *        inside their window.
 *
 * Layer 2 needs `APIOME_DB_SCHEMA_TEST_URL` pointing at a database migrated to the current head
 * (CI's `schema` job in .github/workflows/apiome-db.yml starts one); without it the block is
 * skipped. Each test runs in a transaction that is rolled back. Locally:
 *
 *     createdb apiome_t && node dist/cli.js migrate --database-url postgresql://localhost/apiome_t
 *     APIOME_DB_SCHEMA_TEST_URL=postgresql://localhost/apiome_t yarn vitest run test/mcp-usage-sweep-retention.test.ts
 */

import fs from "node:fs/promises";
import path from "node:path";

import pg from "pg";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V429__mcp_usage_sweep_retention_7206.sql";
const PREVIOUS = "V428__mcp_listed_at_and_project_listing_7205.sql";
const V271 = "V271__agent_invocations_agx_3_3.sql";
const SCHEMA_TEST_URL = process.env.APIOME_DB_SCHEMA_TEST_URL?.trim() ?? "";

/** A migration's SQL with `--` comments stripped and whitespace collapsed, lower-cased. */
async function codeOf(file: string): Promise<string> {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** One `CREATE OR REPLACE FUNCTION <name>(` … `$$ LANGUAGE …;` statement of a migration file. */
function functionSql(sql: string, name: string): string {
  const start = sql.indexOf(`CREATE OR REPLACE FUNCTION ${name}(`);
  expect(start, name).toBeGreaterThan(-1);
  const end = sql.indexOf("$$ LANGUAGE", start);
  return sql.slice(start, sql.indexOf(";", end) + 1);
}

describe("V429: MCP usage sweep retention", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows V428", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf(PREVIOUS);
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(MIGRATION)).toBe(previous + 1);
  });

  it("indexes every time-ordered purge and the incremental rollup", () => {
    for (const index of [
      "create index if not exists idx_upstream_credential_uses_used_at on upstream_credential_uses (used_at)",
      "create index if not exists idx_mcp_access_audit_at on mcp_access_audit (at)",
      "create index if not exists idx_mcp_capability_denials_at on mcp_capability_denials (at)",
      "create index if not exists idx_agent_invocations_day_time on agent_invocations (invoked_day, invoked_at)",
    ]) {
      expect(code).toContain(index);
    }
  });

  it("drops the single-column day index only after its covering replacement", () => {
    const create = code.indexOf("idx_agent_invocations_day_time on");
    const drop = code.indexOf("drop index if exists idx_agent_invocations_day;");
    expect(create).toBeGreaterThan(-1);
    expect(drop).toBeGreaterThan(create);
  });

  it("replaces the two signatures it changes instead of overloading them", () => {
    expect(code).toContain("drop function if exists rollup_agent_invocations(date, timestamptz);");
    expect(code).toContain("drop function if exists purge_upstream_credential_uses(integer);");
    expect(code).toContain("create or replace function rollup_agent_invocations( p_day date, p_now timestamptz default current_timestamp, p_since timestamptz default null )");
    expect(code).toContain("create or replace function purge_upstream_credential_uses( p_retention_days integer default 90, p_batch integer default 10000, p_now timestamptz default current_timestamp )");
  });

  it("bounds every purge by a batch, oldest first", () => {
    for (const name of [
      "purge_agent_invocations",
      "purge_agent_invocation_rollups",
      "purge_upstream_credential_uses",
      "purge_mcp_access_audit",
      "purge_mcp_capability_denials",
    ]) {
      const start = code.indexOf(`create or replace function ${name}(`);
      const body = code.slice(start, code.indexOf("$$ language", start));
      expect(body, name).toContain("limit greatest(p_batch, 1)");
      expect(body, name).toMatch(/order by [a-z]\.(invoked_at|day|used_at|at)\b/);
    }
  });

  it("keeps the raw purge on finalized days only", () => {
    const start = code.indexOf("create or replace function purge_agent_invocations(");
    const body = code.slice(start, code.indexOf("$$ language", start));
    expect(body).toContain("d.day = i.invoked_day and d.finalized_at is not null");
    expect(body).toContain("case when r.raw_cutoff is not null then least(r.raw_cutoff, v_final_end) end");
  });
});

/** The rollup columns compared between the V271 and V429 functions (everything but computed_at). */
const DAILY_COLUMNS =
  "tenant_id, day, key_id, toolset_id, tool_name, target, calls, success_calls, upstream_errors, " +
  "validation_failures, quota_rejections, internal_errors, latency_p50_ms, latency_p95_ms, latency_p99_ms, " +
  "latency_max_ms, latency_sum_ms, request_bytes, response_bytes";

describe.skipIf(!SCHEMA_TEST_URL)("V429 on a migrated database", () => {
  let client: pg.Client;
  let free = "";
  let short = "";
  let forever = "";
  const toolset = "00000000-0000-4000-8000-00000000a001";
  const keys = {
    free: ["00000000-0000-4000-8000-0000000000f1", "00000000-0000-4000-8000-0000000000f2"],
    short: ["00000000-0000-4000-8000-0000000000e1"],
    forever: ["00000000-0000-4000-8000-0000000000d1"],
  };

  beforeAll(async () => {
    client = new pg.Client({ connectionString: SCHEMA_TEST_URL });
    await client.connect();
  });
  afterAll(async () => {
    await client.end();
  });

  beforeEach(async () => {
    await client.query("BEGIN");
    // The rollup bookkeeping is global (per day, not per tenant): start from empty tables.
    await client.query(
      "DELETE FROM apiome.agent_invocation_samples; DELETE FROM apiome.agent_invocations; " +
        "DELETE FROM apiome.agent_invocation_daily; DELETE FROM apiome.agent_invocation_rollup_days",
    );
    free = await addTenant(null);
    short = await addTenant(2);
    forever = await addTenant(-1);
    await loadLegacyFunctions();
  });
  afterEach(async () => {
    await client.query("ROLLBACK");
  });

  /** A tenant with no license (Free: 7 days) or a license keeping raw rows `rawDays` days. */
  async function addTenant(rawDays: number | null): Promise<string> {
    const tag = Math.random().toString(36).slice(2, 10);
    const tenant = (
      await client.query("INSERT INTO apiome.tenants (name, slug) VALUES ('Sweep', $1) RETURNING id", [`sweep-${tag}`])
    ).rows[0].id as string;
    await client.query("DELETE FROM apiome.tenant_licenses WHERE tenant_id = $1", [tenant]);
    if (rawDays !== null) {
      const license = (
        await client.query(
          `INSERT INTO apiome.licenses (name, license_type, seats) VALUES ($1, 'paid', $2::jsonb) RETURNING id`,
          [`sweep ${tag}`, JSON.stringify({ agent_invocation_retention_days: rawDays, agent_usage_rollup_retention_days: 3 })],
        )
      ).rows[0].id as string;
      await client.query("INSERT INTO apiome.tenant_licenses (tenant_id, license_id) VALUES ($1, $2)", [tenant, license]);
    }
    return tenant;
  }

  /** V271's rollup and purge functions, renamed into pg_temp, as the reference implementation. */
  async function loadLegacyFunctions(): Promise<void> {
    const sql = await fs.readFile(path.join(SCRIPTS_DIR, V271), "utf8");
    for (const name of ["rollup_agent_invocations", "rollup_agent_invocation_days", "purge_agent_invocations"]) {
      const statement = functionSql(sql, name)
        .replace(`CREATE OR REPLACE FUNCTION ${name}(`, `CREATE OR REPLACE FUNCTION pg_temp.legacy_${name}(`)
        .replaceAll("apiome.rollup_agent_invocations(", "pg_temp.legacy_rollup_agent_invocations(");
      await client.query(statement);
    }
  }

  /** A revision to point mcp_access_audit rows at. */
  async function addVersion(): Promise<string> {
    const tag = Math.random().toString(36).slice(2, 10);
    const user = (
      await client.query("INSERT INTO apiome.users (name, email, password) VALUES ('Sweep', $1, 'x') RETURNING id", [
        `sweep-${tag}@apiome.local`,
      ])
    ).rows[0].id as string;
    const project = (
      await client.query("INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES ($1, $2, 'Sweep', $3) RETURNING id", [
        free,
        user,
        `sweep-${tag}`,
      ])
    ).rows[0].id as string;
    return (
      await client.query(
        "INSERT INTO apiome.versions (project_id, creator_id, version_id, description) VALUES ($1, $2, '1.0.0', 'Sweep') RETURNING id",
        [project, user],
      )
    ).rows[0].id as string;
  }

  /** One row every `step` going back from `now` in each audit table (the newest is `now` itself). */
  async function addAuditRows(
    now: string,
    counts: { credentialUses: number; accessAudit: number; denials: number },
    step = "1 day",
  ): Promise<void> {
    const version = await addVersion();
    await client.query(
      `INSERT INTO apiome.upstream_credential_uses (tenant_id, credential_id, toolset_id, outcome, used_at)
       SELECT $1, $2, $2, 'injected', $3::timestamptz - g * $5::interval FROM generate_series(0, $4 - 1) g`,
      [free, toolset, now, counts.credentialUses, step],
    );
    await client.query(
      `INSERT INTO apiome.mcp_access_audit (tool, spec_id, at, success)
       SELECT 'spec.describe', $1, $2::timestamptz - g * $4::interval, true FROM generate_series(0, $3 - 1) g`,
      [version, now, counts.accessAudit, step],
    );
    await client.query(
      `INSERT INTO apiome.mcp_capability_denials (tenant_id, tool_id, at, transport, reason)
       SELECT $1, 'spec.search', $2::timestamptz - g * $4::interval, 'http', 'not_granted' FROM generate_series(0, $3 - 1) g`,
      [free, now, counts.denials, step],
    );
  }

  /**
   * `n` calls spread evenly over [from, to) for one tenant: alternating keys, three tools, both
   * targets, every outcome, and latencies and sizes that vary per row.
   */
  async function addCalls(tenant: string, tenantKeys: string[], from: string, to: string, n: number): Promise<void> {
    await client.query(
      `INSERT INTO apiome.agent_invocations
         (tenant_id, key_id, toolset_id, tool_name, target, invoked_at, latency_ms, outcome, error_code,
          http_status, request_bytes, response_bytes)
       SELECT $1, ($2::uuid[])[1 + g % cardinality($2::uuid[])], $3, 'tool_' || (g % 3),
              CASE WHEN g % 7 = 0 THEN 'mock' ELSE 'prod' END,
              $4::timestamptz + (($5::timestamptz - $4::timestamptz) * g / $6),
              (g * 7919) % 2003,
              (ARRAY['success','success','upstream_error','validation_failure','quota_rejected','internal_error'])[1 + g % 6],
              CASE WHEN g % 6 < 2 THEN NULL ELSE 'some_error' END,
              CASE WHEN g % 6 = 2 THEN 502 ELSE 200 END,
              (g * 31) % 4096, (g * 17) % 65536
       FROM generate_series(0, $6 - 1) g`,
      [tenant, tenantKeys, toolset, from, to, n],
    );
  }

  /** The rollup tables, comparable across runs. */
  async function rollups(): Promise<{ daily: unknown[]; days: unknown[] }> {
    const daily = await client.query(`SELECT ${DAILY_COLUMNS} FROM apiome.agent_invocation_daily ORDER BY ${DAILY_COLUMNS}`);
    const days = await client.query(
      "SELECT day::text, rolled_up_at, finalized_at FROM apiome.agent_invocation_rollup_days ORDER BY day",
    );
    return { daily: daily.rows, days: days.rows };
  }

  /** What the apiome-mcp sweep does for its rollups: one call per open day. */
  async function rollUpLikeTheSweep(now: string, grace = "6 hours"): Promise<number> {
    const days = await client.query("SELECT d::text AS d FROM apiome.agent_invocation_open_days($1) d", [now]);
    for (const row of days.rows) {
      await client.query("SELECT apiome.rollup_agent_invocation_day($1, $2, $3)", [row.d, now, grace]);
    }
    return days.rowCount ?? 0;
  }

  /**
   * Three ticks over a day and a half, with calls written between them — including calls that
   * started before the previous tick but were written after it (inside the grace period).
   */
  async function scenario(rollUp: (now: string) => Promise<unknown>): Promise<{ daily: unknown[]; days: unknown[] }> {
    await rollUp("2026-06-15T10:00:00Z");
    await addCalls(free, keys.free, "2026-06-15T07:30:00Z", "2026-06-15T13:00:00Z", 400);
    await addCalls(short, keys.short, "2026-06-15T12:00:00Z", "2026-06-15T13:00:00Z", 50);
    await rollUp("2026-06-15T13:00:00Z");
    await addCalls(forever, keys.forever, "2026-06-15T23:00:00Z", "2026-06-16T05:00:00Z", 300);
    await rollUp("2026-06-16T07:00:00Z");
    return rollups();
  }

  async function seedHistory(): Promise<void> {
    await addCalls(free, keys.free, "2026-06-01T00:00:00Z", "2026-06-15T09:00:00Z", 3000);
    await addCalls(short, keys.short, "2026-06-10T00:00:00Z", "2026-06-15T09:00:00Z", 1000);
    await addCalls(forever, keys.forever, "2026-06-05T00:00:00Z", "2026-06-15T09:00:00Z", 1000);
  }

  it("writes the same rollups as V271, value for value, over incremental ticks", async () => {
    await seedHistory();
    await client.query("SAVEPOINT before_ticks");
    const legacy = await scenario((now) =>
      client.query("SELECT pg_temp.legacy_rollup_agent_invocation_days($1, INTERVAL '6 hours')", [now]),
    );
    await client.query("ROLLBACK TO SAVEPOINT before_ticks");
    const sweep = await scenario(rollUpLikeTheSweep);
    await client.query("ROLLBACK TO SAVEPOINT before_ticks");
    const wrapper = await scenario((now) =>
      client.query("SELECT apiome.rollup_agent_invocation_days($1, INTERVAL '6 hours')", [now]),
    );

    expect(legacy.daily.length).toBeGreaterThan(100);
    expect(sweep).toEqual(legacy);
    expect(wrapper).toEqual(legacy);
  });

  it("recomputes only the groups with a call since the previous rollup minus the grace", async () => {
    await addCalls(free, keys.free, "2026-06-15T00:00:00Z", "2026-06-15T09:00:00Z", 600);
    await addCalls(short, keys.short, "2026-06-15T00:00:00Z", "2026-06-15T02:00:00Z", 60);
    await rollUpLikeTheSweep("2026-06-15T10:00:00Z");
    await addCalls(free, keys.free, "2026-06-15T10:00:00Z", "2026-06-15T11:00:00Z", 30);
    await rollUpLikeTheSweep("2026-06-15T11:00:00Z");

    const stamps = await client.query(
      "SELECT tenant_id, computed_at FROM apiome.agent_invocation_daily WHERE day = '2026-06-15' GROUP BY 1, 2",
    );
    const byTenant = Object.fromEntries(stamps.rows.map((row) => [row.tenant_id, (row.computed_at as Date).toISOString()]));
    expect(byTenant[free]).toBe("2026-06-15T11:00:00.000Z");
    // The short tenant's last call was at 02:00, before 10:00 − 6 h: its groups were left as they were.
    expect(byTenant[short]).toBe("2026-06-15T10:00:00.000Z");
  });

  it("finds the open days from the newest finalized day, reaching back to any raw day not finalized", async () => {
    expect((await client.query("SELECT count(*)::int AS n FROM apiome.agent_invocation_open_days('2026-06-15T10:00:00Z')")).rows[0].n).toBe(0);
    await addCalls(free, keys.free, "2026-06-12T00:00:00Z", "2026-06-15T09:00:00Z", 300);
    const first = await client.query("SELECT d::text AS d FROM apiome.agent_invocation_open_days('2026-06-15T10:00:00Z') d");
    expect(first.rows.map((row) => row.d)).toEqual(["2026-06-12", "2026-06-13", "2026-06-14", "2026-06-15"]);

    await rollUpLikeTheSweep("2026-06-15T10:00:00Z");
    const next = await client.query("SELECT d::text AS d FROM apiome.agent_invocation_open_days('2026-06-15T11:00:00Z') d");
    expect(next.rows.map((row) => row.d)).toEqual(["2026-06-15"]);

    // A call recorded late on a day before every rolled-up day is still found.
    await addCalls(free, keys.free, "2026-06-02T00:00:00Z", "2026-06-02T01:00:00Z", 3);
    const reach = await client.query("SELECT min(d)::text AS d FROM apiome.agent_invocation_open_days('2026-06-15T11:00:00Z') d");
    expect(reach.rows[0].d).toBe("2026-06-02");
  });

  it("purges exactly V271's rows, batch by batch, oldest first", async () => {
    await seedHistory();
    await rollUpLikeTheSweep("2026-06-16T07:00:00Z");
    const now = "2026-06-16T07:00:00Z";

    await client.query("SAVEPOINT before_purge");
    await client.query("SELECT pg_temp.legacy_purge_agent_invocations($1, 1000000)", [now]);
    const legacyKept = (await client.query("SELECT id FROM apiome.agent_invocations ORDER BY id")).rows;
    await client.query("ROLLBACK TO SAVEPOINT before_purge");

    const batches: number[] = [];
    for (;;) {
      const n = (await client.query("SELECT apiome.purge_agent_invocations($1, 500) AS n", [now])).rows[0].n as number;
      batches.push(n);
      if (n < 500) break;
    }
    const kept = (await client.query("SELECT id FROM apiome.agent_invocations ORDER BY id")).rows;
    expect(kept).toEqual(legacyKept);
    expect(batches.length).toBeGreaterThan(2);
    expect(batches.slice(0, -1).every((n) => n === 500)).toBe(true);

    const oldest = await client.query(
      "SELECT tenant_id, min(invoked_at) AS oldest FROM apiome.agent_invocations GROUP BY tenant_id",
    );
    const oldestBy = Object.fromEntries(oldest.rows.map((row) => [row.tenant_id, (row.oldest as Date).toISOString()]));
    expect(oldestBy[free] >= "2026-06-09T07:00:00.000Z").toBe(true);
    expect(oldestBy[short] >= "2026-06-14T07:00:00.000Z").toBe(true);
    expect(oldestBy[forever] < "2026-06-06T00:00:00.000Z").toBe(true);
  });

  it("never purges a raw row of a day that is not finalized", async () => {
    await addCalls(short, keys.short, "2026-06-10T00:00:00Z", "2026-06-11T00:00:00Z", 100);
    // Nothing rolled up yet: no day is final.
    expect((await client.query("SELECT apiome.purge_agent_invocations('2026-06-20T00:00:00Z', 1000) AS n")).rows[0].n).toBe(0);
  });

  it("reads index ranges only when there is nothing to purge", async () => {
    await seedHistory();
    await rollUpLikeTheSweep("2026-06-16T07:00:00Z");
    const now = "2026-06-16T07:00:00Z";
    await client.query("SELECT apiome.purge_agent_invocations($1, 1000000)", [now]);
    await client.query("SELECT apiome.purge_agent_invocation_rollups($1, 1000000)", [now]);
    // 8,000 rows inside every audit window (one every 10 minutes, about 56 days): enough pages
    // that a sequential scan would be a real cost.
    await addAuditRows(now, { credentialUses: 8000, accessAudit: 8000, denials: 8000 }, "10 minutes");
    for (const table of ["agent_invocations", "agent_invocation_daily", "upstream_credential_uses", "mcp_access_audit", "mcp_capability_denials"]) {
      await client.query(`ANALYZE apiome.${table}`);
    }

    const tables = ["agent_invocations", "agent_invocation_daily", "upstream_credential_uses", "mcp_access_audit", "mcp_capability_denials"];
    const stats = async () =>
      Object.fromEntries(
        (
          await client.query(
            "SELECT relname, seq_scan, coalesce(idx_tup_fetch, 0) + 0 AS fetched FROM pg_stat_xact_user_tables WHERE schemaname = 'apiome' AND relname = ANY($1)",
            [tables],
          )
        ).rows.map((row) => [row.relname, { seq: Number(row.seq_scan), fetched: Number(row.fetched) }]),
      );
    const before = await stats();
    await rollUpLikeTheSweep(now);
    for (const statement of [
      "SELECT apiome.purge_agent_invocations($1, 10000)",
      "SELECT apiome.purge_agent_invocation_rollups($1, 10000)",
      "SELECT apiome.purge_upstream_credential_uses(90, 10000, $1)",
      "SELECT apiome.purge_mcp_access_audit(365, 10000, $1)",
      "SELECT apiome.purge_mcp_capability_denials(90, 10000, $1)",
    ]) {
      expect(Object.values((await client.query(statement, [now])).rows[0])).toEqual([0]);
    }
    const after = await stats();
    for (const table of tables) {
      const was = before[table] ?? { seq: 0, fetched: 0 };
      const now_ = after[table] ?? { seq: 0, fetched: 0 };
      expect(now_.seq - was.seq, `${table} sequential scans`).toBe(0);
    }
    // Loose scans: a few index descents per tenant with rows, not a pass over the retained rows.
    const raw = (await client.query("SELECT count(*)::int AS n FROM apiome.agent_invocations")).rows[0].n as number;
    expect(raw).toBeGreaterThan(1000);
    expect(after.agent_invocations.fetched - (before.agent_invocations?.fetched ?? 0)).toBeLessThan(50);
  });

  it("purges credential uses, access audit and capability denials in batches, keeping their windows", async () => {
    const now = "2026-06-16T00:00:00Z";
    await addAuditRows(now, { credentialUses: 120, accessAudit: 400, denials: 120 });

    const drain = async (statement: string): Promise<number[]> => {
      const batches: number[] = [];
      for (;;) {
        const n = (await client.query(statement, [now])).rows[0].n as number;
        batches.push(n);
        if (n < 7) return batches;
      }
    };
    const ages = async (table: string, column: string) =>
      (
        await client.query(
          `SELECT max(($1::timestamptz - ${column}))::text AS oldest, count(*)::int AS n FROM apiome.${table} WHERE ${column} <= $1::timestamptz`,
          [now],
        )
      ).rows[0];

    expect(await drain("SELECT apiome.purge_upstream_credential_uses(90, 7, $1) AS n")).toEqual([7, 7, 7, 7, 1]);
    expect(await ages("upstream_credential_uses", "used_at")).toEqual({ oldest: "90 days", n: 91 });
    expect((await drain("SELECT apiome.purge_mcp_access_audit(365, 7, $1) AS n")).reduce((a, b) => a + b)).toBe(34);
    expect(await ages("mcp_access_audit", "at")).toEqual({ oldest: "365 days", n: 366 });
    expect((await drain("SELECT apiome.purge_mcp_capability_denials(90, 7, $1) AS n")).reduce((a, b) => a + b)).toBe(29);
    expect(await ages("mcp_capability_denials", "at")).toEqual({ oldest: "90 days", n: 91 });
  });

  it("keeps agent_usage_retention's results", async () => {
    const rows = await client.query(
      "SELECT tenant_id, raw_cutoff, rollup_cutoff::text AS rollup_cutoff FROM apiome.agent_usage_retention('2026-06-16T00:00:00Z') WHERE tenant_id = ANY($1)",
      [[free, short, forever]],
    );
    const by = Object.fromEntries(rows.rows.map((row) => [row.tenant_id, row]));
    expect((by[free].raw_cutoff as Date).toISOString()).toBe("2026-06-09T00:00:00.000Z");
    expect(by[free].rollup_cutoff).toBe("2026-03-18");
    expect((by[short].raw_cutoff as Date).toISOString()).toBe("2026-06-14T00:00:00.000Z");
    expect(by[short].rollup_cutoff).toBe("2026-06-13");
    expect(by[forever].raw_cutoff).toBeNull();
  });
});
