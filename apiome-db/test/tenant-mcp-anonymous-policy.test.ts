/**
 * Structural assertions over the anonymous MCP call policy migration (#4772, MTG-2.3).
 *
 * V165 extends tenant_mcp_policies / tenant_mcp_policy_tools with allow_anonymous_mcp
 * and anonymous_enabled (defaults true). Runtime binding is env-based in apiome-mcp.
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V165__tenant_mcp_anonymous_policy_4772.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("tenant MCP anonymous policy migration", () => {
  it("is present in scripts/ and ordered after V164", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V164__mcp_capability_denials_4773.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("documents rollback drops for up/down clean", () => {
    expect(lower).toContain(
      "alter table apiome.tenant_mcp_policy_tools drop column if exists anonymous_enabled",
    );
    expect(lower).toContain(
      "alter table apiome.tenant_mcp_policies drop column if exists allow_anonymous_mcp",
    );
  });

  it("does not create new tables", () => {
    expect(lower).not.toMatch(/create table/);
  });

  describe("tenant_mcp_policies.allow_anonymous_mcp", () => {
    it("adds boolean NOT NULL DEFAULT true idempotently", () => {
      expect(lower).toMatch(
        /add column if not exists allow_anonymous_mcp boolean not null default true/,
      );
    });

    it("documents kill-switch semantics and host-tenant binding", () => {
      expect(lower).toMatch(/comment on column tenant_mcp_policies\.allow_anonymous_mcp is/);
      expect(sql).toMatch(/anonymous/i);
      expect(sql).toMatch(/APIOME_MCP_ANONYMOUS_POLICY_TENANT_ID/);
      expect(sql).toMatch(/Authenticated keys are unaffected/i);
    });
  });

  describe("tenant_mcp_policy_tools.anonymous_enabled", () => {
    it("adds boolean NOT NULL DEFAULT true idempotently", () => {
      expect(lower).toMatch(
        /add column if not exists anonymous_enabled boolean not null default true/,
      );
    });

    it("documents independence from ceiling and private-spec key requirement", () => {
      expect(lower).toMatch(
        /comment on column tenant_mcp_policy_tools\.anonymous_enabled is/,
      );
      expect(sql).toMatch(/Independent of in_ceiling/i);
      expect(sql).toMatch(/Private-spec tools still require API keys/i);
    });
  });
});
