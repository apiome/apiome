/**
 * Structural assertions over the sign-up policy migration (#5653, SGN-1.4).
 *
 * V274 creates `apiome.signup_policy` — the installation's stored sign-up policy, a singleton
 * that overlays the `AUTH_SIGNUP_DISABLED` env flag (no row ⇒ env governs) — and
 * `apiome.signup_policy_audit`, the append-only ledger apiome-rest writes in the same
 * transaction as every change.
 *
 * These are DB-free contract tests pinning the migration's shape: the singleton guard, the mode
 * enum guard, the bounded domain list, the touch trigger, the ledger, and the env-fallback
 * documentation the apiome-ui / apiome-rest policy readers depend on.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V274__signup_policy_sgn_1_4.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("signup_policy migration (SGN-1.4)", () => {
  it("is present in scripts/ and ordered after V273", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V273__agent_toolset_enrichment_agx_1_3.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("is installation-wide, not tenant-scoped", () => {
    expect(lower).not.toMatch(/tenant_id\s+uuid/);
    expect(lower).not.toMatch(/references\s+apiome\.tenants/);
  });

  it("documents the rollback drops", () => {
    expect(lower).toContain("drop table if exists apiome.signup_policy cascade");
    expect(lower).toContain("drop table if exists apiome.signup_policy_audit");
    expect(lower).toContain(
      "drop function if exists apiome.update_signup_policy_updated_at()",
    );
  });

  describe("signup_policy", () => {
    it("is a singleton: a boolean key that can only be TRUE", () => {
      expect(lower).toMatch(/create table if not exists apiome\.signup_policy \(/);
      expect(lower).toMatch(/singleton\s+boolean\s+primary key\s+default\s+true/);
      expect(lower).toMatch(
        /constraint signup_policy_singleton_check check \(singleton\)/,
      );
    });

    it("guards the mode vocabulary", () => {
      expect(lower).toMatch(/mode\s+text\s+not null/);
      expect(lower).toContain("check (mode in ('open', 'invite_only', 'closed'))");
    });

    it("stores allowed domains as a bounded array that defaults to empty", () => {
      expect(lower).toMatch(
        /allowed_email_domains\s+text\[\]\s+not null\s+default\s+'\{\}'::text\[\]/,
      );
      expect(lower).toContain("cardinality(allowed_email_domains) <= 200");
    });

    it("seeds no row, so env keeps governing until a policy is saved", () => {
      expect(lower).not.toContain("insert into apiome.signup_policy");
    });

    it("keeps updated_at current with a BEFORE UPDATE trigger", () => {
      expect(lower).toContain(
        "create or replace function update_signup_policy_updated_at()",
      );
      expect(lower).toMatch(
        /create trigger trigger_update_signup_policy_updated_at\s+before update on apiome\.signup_policy/,
      );
    });
  });

  describe("signup_policy_audit", () => {
    it("records the action, the actor and the policy before and after", () => {
      expect(lower).toMatch(
        /create table if not exists apiome\.signup_policy_audit \(/,
      );
      expect(lower).toMatch(/actor\s+text/);
      expect(lower).toMatch(/before_policy\s+jsonb/);
      expect(lower).toMatch(/after_policy\s+jsonb/);
      expect(lower).toContain("check (action in ('updated', 'cleared'))");
    });

    it("is indexed newest-first", () => {
      expect(lower).toMatch(
        /create index if not exists idx_signup_policy_audit_created_at\s+on apiome\.signup_policy_audit \(created_at desc\)/,
      );
    });
  });

  describe("documentation", () => {
    it("documents both tables and the env fallback", () => {
      expect(lower).toContain("comment on table apiome.signup_policy is");
      expect(lower).toContain("comment on table apiome.signup_policy_audit is");
      expect(sql).toContain("AUTH_SIGNUP_DISABLED");
      expect(sql).toContain("#5653");
    });
  });
});
