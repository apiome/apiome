/**
 * Structural assertions over the SSO just-in-time provisioning migration (EID-1.3, #5013).
 *
 * V394 makes a workspace mandatory for every SSO provider without deleting one that has none,
 * records where a membership came from, and adds the inbox type owners receive when a sign-in is
 * blocked by the seat limit. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V394__sso_jit_provisioning_5013.sql";

let sql = "";

beforeAll(async () => {
  const raw = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  // Compare against the statements only, so prose in a comment cannot satisfy an assertion.
  sql = raw
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n")
    .toLowerCase();
});

describe("SSO just-in-time provisioning migration (EID-1.3)", () => {
  it("is present in scripts/ and ordered after V393", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V393__sso_domain_verification_5012.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(sql).toContain("set search_path to apiome, public");
  });

  it("requires a workspace on every new or changed provider", () => {
    expect(sql).toMatch(
      /add constraint sso_provider_tenant_required_ck check \(tenant_id is not null\) not valid;/,
    );
    expect(sql).toContain("validate constraint sso_provider_tenant_required_ck");
  });

  it("switches a workspace-less provider off before the rule exists, and never deletes one", () => {
    const disable = sql.indexOf("set enabled = false");
    expect(disable).toBeGreaterThan(-1);
    expect(disable).toBeLessThan(sql.indexOf("add constraint sso_provider_tenant_required_ck"));
    expect(sql).toMatch(/where tenant_id is null and enabled;/);
    expect(sql).not.toMatch(/delete from apiome\.sso_provider/);
  });

  it("records where a membership came from", () => {
    expect(sql).toMatch(
      /alter table apiome\.tenant_users\s+add column if not exists provisioned_by varchar\(64\);/,
    );
  });

  it("adds the seat-cap inbox type and keeps every earlier one", () => {
    expect(sql).toContain("'seat_cap_blocked_sso'");
    for (const type of [
      "mention",
      "review_requested",
      "review_decision",
      "thread_resolved",
      "version_published",
      "export_auto_halted",
      "sunset_still_used",
      "owner_finding",
      "owner_breaking_change",
      "owner_verification_drift",
      "owner_gate_blocked",
      "owner_trust_drift",
      "owner_shadow_api",
      "owner_sync_failed",
    ]) {
      expect(sql).toContain(`'${type}'`);
    }
  });

  it("is idempotent", () => {
    expect(sql).toMatch(/if not exists \(\s*select 1 from pg_constraint/);
    expect(sql).toContain("add column if not exists provisioned_by");
    expect(sql).toContain("drop constraint if exists notifications_type_check");
  });
});
