/**
 * Structural assertions over the tenant MCP policy change audit migration (#4786, MTG-5.2).
 *
 * V166 adds `apiome.tenant_mcp_policy_changes` — append-only before/after JSONB
 * snapshots written by apiome-rest on every non-noop admin PUT. Retention is
 * documented in comments only (no sweeper in this ticket).
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V166__tenant_mcp_policy_changes_4786.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("Tenant MCP policy changes migration", () => {
  it("is present in scripts/ and ordered after V165", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V165__tenant_mcp_anonymous_policy_4772.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates tenant_mcp_policy_changes idempotently", () => {
    expect(lower).toMatch(/create table if not exists tenant_mcp_policy_changes/);
  });

  it("documents rollback drop for up/down clean", () => {
    expect(lower).toContain("drop table if exists apiome.tenant_mcp_policy_changes");
  });

  it("does not alter live policy tables", () => {
    expect(lower).not.toMatch(/alter table.*tenant_mcp_policies/);
    expect(lower).not.toMatch(/alter table.*tenant_mcp_policy_tools/);
  });

  describe("columns", () => {
    it("requires tenant_id with CASCADE on tenants delete", () => {
      expect(lower).toMatch(
        /tenant_id\s+uuid not null references apiome\.tenants\(id\) on delete cascade/,
      );
    });

    it("has nullable actor_user_id with SET NULL on users delete", () => {
      expect(lower).toMatch(
        /actor_user_id\s+uuid references apiome\.users\(id\) on delete set null/,
      );
    });

    it("has actor_label text", () => {
      expect(lower).toMatch(/actor_label\s+text/);
    });

    it("requires before_policy and after_policy JSONB", () => {
      expect(lower).toMatch(/before_policy\s+jsonb not null/);
      expect(lower).toMatch(/after_policy\s+jsonb not null/);
    });

    it("timestamps changes as created_at with CURRENT_TIMESTAMP default", () => {
      expect(lower).toMatch(
        /created_at\s+timestamptz not null default current_timestamp/,
      );
    });
  });

  describe("indexes", () => {
    it("indexes tenant_id + created_at DESC", () => {
      expect(lower).toContain("idx_tenant_mcp_policy_changes_tenant_at");
      expect(lower).toMatch(
        /on apiome\.tenant_mcp_policy_changes \(tenant_id, created_at desc\)/,
      );
    });
  });

  describe("comments / retention / PII", () => {
    it("documents 90-day retention intent on the table", () => {
      expect(lower).toContain("90 days");
      expect(lower).toContain("purge");
    });

    it("forbids storing secrets", () => {
      expect(lower).toContain("never store");
      expect(lower).toContain("secrets");
    });

    it("has no argument, payload, key, or secret columns", () => {
      const createMatch = lower.match(
        /create table if not exists tenant_mcp_policy_changes\s*\(([\s\S]*?)\);/,
      );
      expect(createMatch).not.toBeNull();
      const cols = createMatch![1];
      expect(cols).not.toMatch(/\barguments?\b/);
      expect(cols).not.toMatch(/\bpayload\b/);
      expect(cols).not.toMatch(/\bauthorization\b/);
      expect(cols).not.toMatch(/\bsecret/);
      expect(cols).not.toMatch(/\bkey_id\b/);
    });
  });
});
