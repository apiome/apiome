/**
 * Structural assertions over the agent invocation audit migration (#4539, AGX-3.3).
 *
 * V271 adds the per-call invocation log, opt-in body samples, daily rollups and per-tier retention.
 * DB-free contract tests pin the rules the ticket's acceptance criteria turn into schema rules:
 *
 *   1. **Metadata only**: no body / header / argument column on `agent_invocations`.
 *   2. **Every outcome is a row**, and every failure carries a machine reason code.
 *   3. **History outlives keys**: no FK on `key_id` / `toolset_id`; rows are write-once.
 *   4. **Bodies are opt-in, sampled and bounded** (rate, 7-day window, 16 KiB, 7-day purge).
 *   5. **Rollups match raw counts**: recomputed per open day, frozen once final.
 *   6. **Pruning never touches rollups** and only removes rows of finalized days.
 *   7. **Retention follows the license tier** (`licenses.seats`, fill-if-absent).
 *
 * These must stay in lock-step with apiome-mcp's `apiome_mcp.agent_invocations` and
 * `apiome_mcp.agent_usage_sweep`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V271__agent_invocations_agx_3_3.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

/**
 * The body of one `CREATE TABLE`, up to its closing `);` at the start of a line.
 *
 * @param name The table name.
 * @returns The lower-cased, whitespace-collapsed table body.
 */
function tableBody(name: string): string {
  const start = ddl.indexOf(`create table if not exists ${name} (`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf(" ); ", start));
}

/**
 * The body of one `CREATE OR REPLACE FUNCTION`, up to its `language` clause.
 *
 * @param name The function name.
 * @returns The lower-cased, whitespace-collapsed function source.
 */
function functionBody(name: string): string {
  const start = ddl.indexOf(`create or replace function ${name}(`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf(" language ", start));
}

describe("agent invocations migration (AGX-3.3)", () => {
  it("is present in scripts/ and ordered after the agent toolsets migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V270__agent_toolsets_agx_1_2.sql"));
  });

  it("targets the apiome schema", () => {
    expect(sql.toLowerCase()).toContain("set search_path to apiome, public");
  });

  describe("rule 1 — metadata only", () => {
    it("records who, what, when, how fast, how it ended and sizes", () => {
      const body = tableBody("agent_invocations");
      for (const column of [
        "tenant_id uuid not null references tenants(id) on delete cascade",
        "key_id uuid not null",
        "toolset_id uuid not null",
        "tool_name varchar(64) not null",
        "target varchar(8) not null",
        "invoked_at timestamptz not null",
        "invoked_day date generated always as ((invoked_at at time zone 'utc')::date) stored",
        "latency_ms integer not null",
        "outcome varchar(24) not null",
        "error_code varchar(64)",
        "http_status smallint",
        "request_bytes bigint not null",
        "response_bytes bigint not null",
        "sampled boolean not null default false",
      ]) {
        expect(body).toContain(column);
      }
    });

    it("has no body, header, argument or free-text column", () => {
      const body = tableBody("agent_invocations");
      for (const forbidden of ["body", "header", "argument", "message", "payload", " text"]) {
        expect(body).not.toContain(forbidden);
      }
    });
  });

  describe("rule 2 — every outcome is a row", () => {
    it("enumerates the outcomes", () => {
      expect(tableBody("agent_invocations")).toContain(
        "outcome in ('success', 'upstream_error', 'validation_failure', 'quota_rejected', 'internal_error')",
      );
    });

    it("requires a machine reason code exactly on failure", () => {
      const body = tableBody("agent_invocations");
      expect(body).toContain("check ( (outcome = 'success') = (error_code is null) )");
      expect(body).toContain("check (error_code ~ '^[a-z][a-z0-9_.]{0,63}$')");
    });
  });

  describe("rule 3 — history outlives keys", () => {
    it("does not reference api_keys or agent_toolsets", () => {
      for (const table of ["agent_invocations", "agent_invocation_daily"]) {
        const body = tableBody(table);
        expect(body).not.toContain("references api_keys");
        expect(body).not.toContain("references agent_toolsets");
      }
    });

    it("is write-once", () => {
      expect(ddl).toContain(
        "create trigger trigger_agent_invocations_immutable before update on agent_invocations for each row execute function mcp_forbid_row_mutation()",
      );
      expect(ddl).toContain(
        "create trigger trigger_agent_invocation_samples_immutable before update on agent_invocation_samples",
      );
    });
  });

  describe("rule 4 — bodies are opt-in, sampled and bounded", () => {
    it("adds a default-off capture rate with a required end time", () => {
      expect(ddl).toContain("add column if not exists body_capture_rate numeric(5, 4) not null default 0");
      expect(ddl).toContain("add column if not exists body_capture_until timestamptz");
      expect(ddl).toContain("body_capture_rate >= 0 and body_capture_rate <= 1");
      expect(ddl).toContain("(body_capture_rate = 0 or body_capture_until is not null)");
    });

    it("bounds the capture window to 7 days ahead", () => {
      expect(functionBody("agent_toolsets_body_capture_window")).toContain(
        "new.body_capture_until > current_timestamp + interval '7 days'",
      );
      expect(ddl).toContain(
        "before insert or update of body_capture_rate, body_capture_until on agent_toolsets",
      );
    });

    it("caps each sampled body at 16 KiB and cascades with its invocation", () => {
      const body = tableBody("agent_invocation_samples");
      expect(body).toContain("invocation_id uuid primary key references agent_invocations(id) on delete cascade");
      expect(body).toContain("check (octet_length(request_body) <= 16384)");
      expect(body).toContain("check (octet_length(response_body) <= 16384)");
      expect(body).not.toContain("header");
    });

    it("purges samples after at most 7 days", () => {
      expect(functionBody("purge_agent_invocation_samples")).toContain(
        "captured_at < p_now - least(p_max_age, interval '7 days')",
      );
    });
  });

  describe("rule 5 — rollups match raw counts", () => {
    it("aggregates calls by outcome, latency percentiles and bytes per key/tool/day", () => {
      const body = tableBody("agent_invocation_daily");
      expect(body).toContain("primary key (tenant_id, day, key_id, toolset_id, tool_name, target)");
      expect(body).toContain("errors bigint generated always as (calls - success_calls) stored");
      for (const column of ["latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "latency_max_ms", "request_bytes", "response_bytes"]) {
        expect(body).toContain(column);
      }
      expect(body).toContain(
        "calls = success_calls + upstream_errors + validation_failures + quota_rejections + internal_errors",
      );
    });

    it("recomputes a day from the raw rows and never touches a finalized day", () => {
      const body = functionBody("rollup_agent_invocations");
      expect(body).toContain("where day = p_day and finalized_at is not null ) then return 0");
      expect(body).toContain("from apiome.agent_invocations i where i.invoked_day = p_day");
      expect(body).toContain("on conflict (tenant_id, day, key_id, toolset_id, tool_name, target) do update");
    });

    it("finalizes a day only after it ended plus a grace period", () => {
      expect(functionBody("rollup_agent_invocation_days")).toContain(
        "if ((v_day + 1)::timestamp at time zone 'utc') + p_grace <= p_now then",
      );
    });
  });

  describe("rule 6 — pruning never touches rollups", () => {
    it("deletes only raw rows past retention on finalized days", () => {
      const body = functionBody("purge_agent_invocations");
      expect(body).toContain("delete from apiome.agent_invocations");
      expect(body).toContain("i.invoked_at < r.raw_cutoff");
      expect(body).toContain("d.day = i.invoked_day and d.finalized_at is not null");
      expect(body).not.toContain("agent_invocation_daily");
    });

    it("prunes rollups separately by their own cutoff", () => {
      expect(functionBody("purge_agent_invocation_rollups")).toContain("d.day < r.rollup_cutoff");
    });
  });

  describe("rule 7 — retention follows the license tier", () => {
    it("reads both windows from licenses.seats with Free fallbacks", () => {
      const body = functionBody("agent_usage_retention");
      expect(body).toContain("left join apiome.tenant_licenses tl on tl.tenant_id = t.id");
      expect(body).toContain("else 7 end as raw_days");
      expect(body).toContain("else 90 end as rollup_days");
      expect(body).toContain("when raw_days < 0 then null");
      expect(body).toContain("greatest(raw_days, 1)");
    });

    it.each([
      ["free", 7, 90],
      ["paid", 30, 395],
      ["sponsor", 90, 730],
    ])("seeds the %s tier fill-if-absent", (tier, raw, rollup) => {
      expect(ddl).toContain(
        `'agent_invocation_retention_days', ${raw}, 'agent_usage_rollup_retention_days', ${rollup} ) || seats, updated_at = current_timestamp where license_type = '${tier}'`,
      );
    });
  });
});
