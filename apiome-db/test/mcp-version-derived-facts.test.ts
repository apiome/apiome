/**
 * Structural assertions over the DBP-1.17 (#7200) migration, V425:
 *
 *   - eight derived-fact columns on mcp_endpoint_versions, nullable (NULL = not derived yet);
 *   - the recomputation of each fact as a cheap, parallel-safe function the readers fall back to;
 *   - a set-based derive function, a resumable batch backfill and a verification;
 *   - a write-once guard for the table that lets through exactly one kind of update;
 *   - two indexes for the cross-tenant duplicate hints.
 *
 * Behaviour (backfill resumable and verified, the guard, identical reads before and after) is
 * tested against Postgres in apiome-rest (tests/test_mcp_version_facts_db.py) and was run on the
 * scale database; these tests keep the definitions from drifting.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V425__mcp_version_derived_facts_7200.sql";

const FACTS = [
  "tool_count",
  "resource_count",
  "resource_template_count",
  "prompt_count",
  "has_destructive",
  "read_only_only",
  "max_tool_props",
  "change_count",
];

/** The migration's SQL with `--` comments stripped and whitespace collapsed, lower-cased. */
async function codeOf(file: string): Promise<string> {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** The definition of a function, from its CREATE to the end of its body. */
function functionOf(code: string, signature: string): string {
  const start = code.indexOf(`create or replace function apiome.${signature}`);
  expect(start, signature).toBeGreaterThan(-1);
  return code.slice(start, code.indexOf("$fn$;", start));
}

describe("V425: MCP endpoint version derived facts", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows V424", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf("V424__public_browse_counts_and_name_search_7199.sql");
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(MIGRATION)).toBe(previous + 1);
  });

  describe("columns", () => {
    it("adds the eight facts as nullable columns, so the table is not rewritten", () => {
      for (const column of FACTS) {
        const type = column === "has_destructive" || column === "read_only_only" ? "boolean" : "integer";
        expect(code, column).toContain(`add column if not exists ${column} ${type}`);
        expect(code, column).not.toMatch(new RegExp(`add column if not exists ${column} \\w+[^,;]*(default|not null|generated)`));
      }
    });

    it("keeps the counts non-negative", () => {
      for (const column of FACTS.filter((c) => !c.startsWith("has_") && c !== "read_only_only")) {
        expect(code, column).toContain(`check (${column} >= 0)`);
      }
    });

    it("indexes only the snapshots still to derive", () => {
      expect(code).toContain(
        "create index if not exists idx_mcp_endpoint_versions_facts_pending on apiome.mcp_endpoint_versions (id) where tool_count is null",
      );
    });
  });

  describe("recomputation functions", () => {
    const functions = [
      "mcp_version_kind_count(p_version_id uuid, p_kind text)",
      "mcp_version_has_destructive(p_version_id uuid)",
      "mcp_version_read_only_only(p_version_id uuid)",
      "mcp_version_max_tool_props(p_version_id uuid)",
      "mcp_version_change_count(p_version_id uuid)",
    ];

    it("are PL/pgSQL (not inlined), stable, parallel safe and cheap to the planner", () => {
      for (const signature of functions) {
        const fn = functionOf(code, signature);
        expect(fn, signature).toContain("language plpgsql stable parallel safe cost 10");
      }
    });

    it("carry the catalog's original definitions", () => {
      expect(functionOf(code, functions[0])).toContain(
        "where i.version_id = p_version_id and i.item_type = p_kind",
      );
      // A JSON boolean true — a string "true" is not asserted.
      expect(functionOf(code, functions[1])).toContain(
        "sd.item_type = 'tool' and sd.annotations -> 'destructivehint' = 'true'::jsonb",
      );
      const readOnly = functionOf(code, functions[2]);
      expect(readOnly).toContain("return exists (select 1 from apiome.mcp_capability_items sr");
      expect(readOnly).toContain(
        "and not exists (select 1 from apiome.mcp_capability_items sr where sr.version_id = p_version_id and sr.item_type = 'tool' and sr.annotations -> 'readonlyhint' is distinct from 'true'::jsonb)",
      );
      const props = functionOf(code, functions[3]);
      expect(props).toContain("when jsonb_typeof(tc.input_schema -> 'properties') = 'object'");
      expect(props).toContain("else 0 end)::int");
      expect(functionOf(code, functions[4])).toContain(
        "from apiome.mcp_version_changes c where c.version_id = p_version_id",
      );
    });
  });

  describe("derive, backfill and verify", () => {
    it("derives many snapshots in one statement and skips those that already have facts", () => {
      const fn = functionOf(code, "derive_mcp_version_facts(p_version_ids uuid[])");
      expect(fn).toContain("returns integer language sql");
      expect(fn).toContain("where ci.version_id = any(p_version_ids) group by ci.version_id");
      expect(fn).toContain("where c.version_id = any(p_version_ids) group by c.version_id");
      // A snapshot with no item still gets zeros, false and NULL — not left pending.
      for (const column of ["tool_count", "resource_count", "resource_template_count", "prompt_count", "change_count"]) {
        expect(fn, column).toMatch(new RegExp(`${column} = coalesce\\(\\w\\.${column}, 0\\)`));
      }
      expect(fn).toContain("has_destructive = coalesce(i.has_destructive, false)");
      expect(fn).toContain("read_only_only = coalesce(i.read_only_only, false)");
      expect(fn).toContain("max_tool_props = i.max_tool_props,");
      expect(fn).toContain("and v.tool_count is null returning 1");
    });

    it("counts max_tool_props over tools only, as 0 for a tool without a properties object", () => {
      const fn = functionOf(code, "derive_mcp_version_facts(p_version_ids uuid[])");
      expect(fn).toContain(
        "max(case when ci.item_type <> 'tool' then null when jsonb_typeof(ci.input_schema -> 'properties') = 'object' then (select count(*) from jsonb_object_keys(ci.input_schema -> 'properties')) else 0 end)::int as max_tool_props",
      );
    });

    it("backfills a bounded batch of pending snapshots without waiting on another session", () => {
      const fn = functionOf(code, "backfill_mcp_version_facts(p_limit integer)");
      expect(fn).toContain("select apiome.derive_mcp_version_facts(array(");
      expect(fn).toContain("where v.tool_count is null order by v.id limit greatest(coalesce(p_limit, 0), 0) for update skip locked");
    });

    it("does not backfill inside the migration", () => {
      expect(code).not.toMatch(/select apiome\.backfill_mcp_version_facts\(\d/);
      expect(code).not.toContain("disable trigger");
    });

    it("verifies stored facts against the recomputation functions, for derived snapshots only", () => {
      const fn = functionOf(code, "verify_mcp_version_facts(p_limit integer default 100)");
      for (const column of FACTS) expect(fn, column).toContain(`'${column}', v.${column}`);
      for (const call of [
        "apiome.mcp_version_kind_count(v.id, 'tool')",
        "apiome.mcp_version_kind_count(v.id, 'resource')",
        "apiome.mcp_version_kind_count(v.id, 'resource_template')",
        "apiome.mcp_version_kind_count(v.id, 'prompt')",
        "apiome.mcp_version_has_destructive(v.id)",
        "apiome.mcp_version_read_only_only(v.id)",
        "apiome.mcp_version_max_tool_props(v.id)",
        "apiome.mcp_version_change_count(v.id)",
      ]) {
        expect(fn, call).toContain(call);
      }
      expect(fn).toContain("where v.tool_count is not null and s.facts is distinct from r.facts");
    });
  });

  describe("write-once guard", () => {
    it("gives mcp_endpoint_versions its own guard and leaves the shared one alone", () => {
      expect(code).toContain(
        "create trigger trigger_mcp_endpoint_versions_immutable before update on apiome.mcp_endpoint_versions for each row execute function apiome.mcp_endpoint_versions_forbid_mutation()",
      );
      expect(code).toContain("drop trigger if exists trigger_mcp_endpoint_versions_immutable on apiome.mcp_endpoint_versions");
      expect(code).not.toContain("create or replace function apiome.mcp_forbid_row_mutation");
      expect(code).not.toContain("create or replace function mcp_forbid_row_mutation");
    });

    it("allows only filling the facts of a row that has none, with nothing else changed", () => {
      const fn = functionOf(code, "mcp_endpoint_versions_forbid_mutation()");
      expect(fn).toContain("if old.tool_count is null and new.tool_count is not null then");
      for (const column of FACTS) expect(fn, column).toContain(`v_without_facts.${column} := old.${column};`);
      expect(fn).toContain("if v_without_facts is not distinct from old then return new; end if;");
      // Everything else is refused as before: same message, same SQLSTATE.
      expect(fn).toContain("raise exception 'table %.% is immutable; rows are write-once and cannot be updated'");
      expect(fn).toContain("using errcode = 'restrict_violation'");
    });
  });

  describe("duplicate-hint indexes", () => {
    it("indexes snapshots by fingerprint and published endpoints by their dedup key", () => {
      expect(code).toContain(
        "create index if not exists idx_mcp_endpoint_versions_surface_fingerprint on apiome.mcp_endpoint_versions (surface_fingerprint) where surface_fingerprint is not null",
      );
      expect(code).toContain("create index if not exists idx_mcp_endpoints_published_dedup_key on apiome.mcp_endpoints (");
      expect(code).toContain(
        "(coalesce(lower(substring(endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)')), btrim(endpoint_url, e' \\t\\n\\r')))",
      );
      expect(code).toContain("where published = true and deleted_at is null");
    });

    it("adds three indexes in all, each re-runnable", () => {
      const created = code.match(/create index[^;]*;/g) ?? [];
      expect(created).toHaveLength(3);
      for (const statement of created) expect(statement).toContain("create index if not exists");
    });
  });
});
