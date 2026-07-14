/**
 * Structural assertions over the MCP tenant policy backfill migration (#4769, MTG-1.5).
 *
 * V163 backfills every existing tenant via `seed_tenant_mcp_policy` (default_mode=all,
 * empty tool rows = full MTG-1.1 registry) and affirms non-explicit mcp_api_keys rows
 * to capability_mode=inherit. Upgrade must be a no-op for live MCP clients until an
 * admin edits policy.
 *
 * DB-free contract tests pin the migration shape and documented upgrade path.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V163__mcp_tenant_policy_backfill_4769.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP tenant policy backfill migration (MTG-1.5)", () => {
  it("is present in scripts/ and ordered after V162", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V162__mcp_api_key_capability_grants_4767.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("documents the upgrade path and mcp-quickstart no-break contract", () => {
    expect(sql).toMatch(/upgrade path/i);
    expect(sql).toMatch(/pre-V161\/V162/i);
    expect(sql).toMatch(/V162/i);
    expect(sql).toMatch(/V163/i);
    expect(sql).toMatch(/mcp-quickstart/i);
    expect(sql).toMatch(/default_mode='all'/i);
    expect(sql).toMatch(/ON CONFLICT DO NOTHING/i);
  });

  it("documents rollback as leave-rows / wipe only with V161 tables", () => {
    expect(sql).toMatch(/rollback/i);
    expect(sql).toMatch(/V161/i);
    expect(lower).toContain("do not delete tenant_mcp_policies");
  });

  describe("tenant policy backfill", () => {
    it("loops every existing tenant and calls seed_tenant_mcp_policy", () => {
      expect(lower).toMatch(/for t in select id from apiome\.tenants loop/);
      expect(lower).toMatch(/perform apiome\.seed_tenant_mcp_policy\(t\.id\)/);
    });

    it("relies on full-catalog semantics via default_mode=all (no hardcoded tool ids)", () => {
      expect(sql).toMatch(/empty tool rows/i);
      expect(sql).toMatch(/app\.mcp_tool_registry/);
      expect(lower).not.toMatch(/insert into apiome\.tenant_mcp_policy_tools/);
    });
  });

  describe("mcp_api_keys inherit affirmation", () => {
    it("sets inherit + empty enabled_tools for non-explicit keys", () => {
      expect(lower).toMatch(/update apiome\.mcp_api_keys/);
      expect(lower).toMatch(/capability_mode = 'inherit'/);
      expect(lower).toMatch(/enabled_tools = '\[\]'::jsonb/);
      expect(lower).toMatch(
        /where capability_mode is distinct from 'explicit'/,
      );
    });

    it("documents that explicit (admin-edited) keys are preserved", () => {
      expect(sql).toMatch(/do not touch capability_mode='explicit'/i);
      expect(sql).toMatch(/admin-edited/i);
    });
  });
});
