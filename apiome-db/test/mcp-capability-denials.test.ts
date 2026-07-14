/**
 * Structural assertions over the denied-call audit trail migration (#4773, MTG-2.4).
 *
 * V164 adds `apiome.mcp_capability_denials` — append-only capability denial rows
 * written by apiome-mcp on every authenticated tools/call block. Retention is
 * documented in comments only (no sweeper in this ticket).
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V164__mcp_capability_denials_4773.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP capability denials migration", () => {
  it("is present in scripts/ and ordered after V163", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V163__mcp_tenant_policy_backfill_4769.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates mcp_capability_denials idempotently", () => {
    expect(lower).toMatch(/create table if not exists mcp_capability_denials/);
  });

  it("documents rollback drop for up/down clean", () => {
    expect(lower).toContain("drop table if exists apiome.mcp_capability_denials");
  });

  it("does not alter mcp_access_audit", () => {
    expect(lower).not.toMatch(/alter table.*mcp_access_audit/);
  });

  describe("columns", () => {
    it("has nullable key_id with SET NULL on mcp_api_keys delete", () => {
      expect(lower).toMatch(
        /key_id\s+uuid references apiome\.mcp_api_keys\(id\) on delete set null/,
      );
    });

    it("requires tenant_id with CASCADE on tenants delete", () => {
      expect(lower).toMatch(
        /tenant_id\s+uuid not null references apiome\.tenants\(id\) on delete cascade/,
      );
    });

    it("requires non-empty tool_id", () => {
      expect(lower).toMatch(
        /mcp_capability_denials_tool_id_nonempty[\s\S]*?check \(char_length\(trim\(tool_id\)\) > 0\)/,
      );
    });

    it("timestamps denials as at with CURRENT_TIMESTAMP default", () => {
      expect(lower).toMatch(/at\s+timestamptz not null default current_timestamp/);
    });

    it("constrains transport to stdio | http", () => {
      expect(lower).toMatch(
        /mcp_capability_denials_transport_ck[\s\S]*?check \(transport in \('stdio', 'http'\)\)/,
      );
    });

    it("requires non-empty reason", () => {
      expect(lower).toMatch(
        /mcp_capability_denials_reason_nonempty[\s\S]*?check \(char_length\(trim\(reason\)\) > 0\)/,
      );
    });
  });

  describe("indexes", () => {
    it("indexes tenant_id + at DESC", () => {
      expect(lower).toContain("idx_mcp_capability_denials_tenant_at");
      expect(lower).toMatch(
        /on apiome\.mcp_capability_denials \(tenant_id, at desc\)/,
      );
    });

    it("partial-indexes key_id + at DESC when key_id is present", () => {
      expect(lower).toContain("idx_mcp_capability_denials_key_at");
      expect(lower).toMatch(/where key_id is not null/);
    });

    it("indexes tool_id + at DESC", () => {
      expect(lower).toContain("idx_mcp_capability_denials_tool_at");
      expect(lower).toMatch(
        /on apiome\.mcp_capability_denials \(tool_id, at desc\)/,
      );
    });
  });

  describe("comments / retention / PII", () => {
    it("documents 90-day retention intent on the table", () => {
      expect(lower).toContain("90 days");
      expect(lower).toContain("purge");
    });

    it("forbids storing tool arguments or secrets", () => {
      expect(lower).toContain("never store tool arguments");
      expect(lower).toContain("secrets");
    });

    it("has no argument or payload columns", () => {
      const createMatch = lower.match(
        /create table if not exists mcp_capability_denials\s*\(([\s\S]*?)\);/,
      );
      expect(createMatch).not.toBeNull();
      const cols = createMatch![1];
      expect(cols).not.toMatch(/\barguments?\b/);
      expect(cols).not.toMatch(/\bpayload\b/);
      expect(cols).not.toMatch(/\bauthorization\b/);
      expect(cols).not.toMatch(/\bsecret/);
    });
  });
});
