/**
 * Structural assertions over the agent toolset migration (#4530, AGX-1.2).
 *
 * V270 adds the tool selection & curation model and closes the AGX-2.2 / AGX-3.1 handoffs.
 * DB-free contract tests pin the rules the ticket's acceptance criteria turn into schema rules:
 *
 *   1. **One toolset per version**, scoped to a tenant, targeting `prod` or `mock`.
 *   2. **Tool rows reference operations** by canonical key and record the compiled tool name.
 *   3. **Safe by default**: an enabled write op must carry a confirmation, so even a direct SQL
 *      write cannot skip it.
 *   4. **Handoffs**: orphaned `upstream_credentials` / agent `api_keys` rows are deleted, then both
 *      `toolset_id` columns get a tenant-scoped, cascading foreign key.
 *
 * There is deliberately **no new RBAC resource**: the toolset API reuses `api_keys`.
 *
 * These must stay in lock-step with apiome-rest's `app.agent_toolsets` and its
 * `tests/test_agent_toolsets_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V270__agent_toolsets_agx_1_2.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?;/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

/**
 * The body of one `CREATE TABLE`, up to its closing `);`.
 *
 * @param name The table name.
 * @returns The lower-cased, whitespace-collapsed table body.
 */
function tableBody(name: string): string {
  const start = ddl.indexOf(`create table if not exists ${name} (`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf(");", start));
}

describe("agent toolsets migration (AGX-1.2)", () => {
  it("is present in scripts/ and ordered after the agent keys migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V269__agent_keys_agx_3_1.sql"));
  });

  it("targets the apiome schema", () => {
    expect(sql.toLowerCase()).toContain("set search_path to apiome, public");
  });

  describe("rule 1 — one toolset per published version", () => {
    it("binds the toolset to a tenant and a version, cascading on delete", () => {
      const body = tableBody("agent_toolsets");
      expect(body).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(body).toContain("version_id uuid not null references versions(id) on delete cascade");
      expect(body).toContain("constraint agent_toolsets_version_uq unique (version_id)");
      expect(body).toContain("constraint agent_toolsets_tenant_id_uq unique (tenant_id, id)");
    });

    it("targets prod (default) or mock", () => {
      const body = tableBody("agent_toolsets");
      expect(body).toContain("target varchar(8) not null default 'prod'");
      expect(body).toContain("check (target in ('prod', 'mock'))");
    });
  });

  describe("rule 2 — tool rows reference operations", () => {
    it("keys rows by toolset and canonical operation, with a unique tool name", () => {
      const body = tableBody("agent_toolset_tools");
      expect(body).toContain(
        "toolset_id uuid not null references agent_toolsets(id) on delete cascade",
      );
      expect(body).toContain("operation_key text not null");
      expect(body).toContain("unique (toolset_id, operation_key)");
      expect(body).toContain("unique (toolset_id, tool_name)");
    });

    it("holds tool names to the AGX-1.1 grammar", () => {
      expect(sql).toContain("CHECK (tool_name ~ '^[A-Za-z0-9_-]{1,64}$')");
    });
  });

  describe("rule 3 — safe by default", () => {
    it("requires a confirmation exactly while a write op is enabled", () => {
      const body = tableBody("agent_toolset_tools");
      expect(body).toContain("write_op boolean not null");
      expect(body).toContain(
        "(write_op and enabled and write_confirmed_at is not null) " +
          "or (not (write_op and enabled) and write_confirmed_at is null)",
      );
    });

    it("keeps a departing confirmer from deleting the record of the confirmation", () => {
      expect(tableBody("agent_toolset_tools")).toContain(
        "write_confirmed_by uuid references users(id) on delete set null",
      );
    });
  });

  describe("rule 4 — AGX-2.2 / AGX-3.1 handoffs", () => {
    it("deletes orphans before adding the foreign keys", () => {
      const credentials = ddl.indexOf("delete from upstream_credentials");
      const keys = ddl.indexOf("delete from api_keys");
      expect(credentials).toBeGreaterThanOrEqual(0);
      expect(keys).toBeGreaterThanOrEqual(0);
      expect(ddl.slice(keys, ddl.indexOf(";", keys))).toContain("k.kind = 'agent'");
      const firstFk = ddl.indexOf("add constraint upstream_credentials_toolset_fk");
      expect(Math.max(credentials, keys)).toBeLessThan(firstFk);
    });

    it("adds tenant-scoped, cascading foreign keys idempotently", () => {
      const fk =
        "foreign key (tenant_id, toolset_id) references agent_toolsets (tenant_id, id) on delete cascade";
      expect(ddl.split(fk).length - 1).toBe(2);
      for (const name of ["upstream_credentials_toolset_fk", "api_keys_agent_toolset_fk"]) {
        expect(ddl).toContain(`drop constraint if exists ${name};`);
      }
    });
  });

  it("seeds no RBAC resource", () => {
    expect(ddl).not.toContain("seed_builtin_roles");
    expect(ddl).not.toContain("role_permissions");
  });
});
