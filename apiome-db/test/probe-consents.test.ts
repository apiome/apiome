/**
 * Structural assertions over the probe consent migration (#5939, ASP-4.1).
 *
 * V386 stores who authorized security probes against which verification target, and the
 * write-once report each probe run leaves. DB-free contract tests pin its rules:
 *
 *   1. **Explicit, attributable, bounded consent**: ownership must be declared, approver and
 *      expiry are required, and the expiry follows the approval.
 *   2. **No secrets**: identities carry V211's credential-reference CHECKs.
 *   3. **One live consent per target**, revoked rather than edited.
 *   4. **Tenant-consistent** through composite keys on the target and the evidence run.
 *   5. **Write-once reports**, capped at `observed` on the hosted mock, consent required elsewhere.
 *   6. **Soft references on guarded rows** — no `ON DELETE SET NULL` an immutability trigger rejects.
 *
 * These must stay in lock-step with apiome-rest's `app.probe_consent` / `app.probe_consent_store`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V386__probe_consents_asp_4_1.sql";

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

describe("probe consent migration (ASP-4.1)", () => {
  it("is present in scripts/ and ordered after the stored overlay migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V385__version_overlays_gvm_4_3.sql"));
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("requires an ownership declaration, an approver and a later expiry", () => {
    expect(ddl).toContain("check (ownership_declared)");
    expect(ddl).toContain("approved_by uuid not null references users(id) on delete cascade");
    expect(ddl).toContain("expires_at timestamptz not null");
    expect(ddl).toContain("check (expires_at > approved_at)");
  });

  it("accepts only the known profiles", () => {
    expect(ddl).toContain("profiles_allowed <@ array['passive', 'safe-active', 'payload']::text[]");
    expect(ddl).toContain("check (profile in ('passive', 'safe-active', 'payload'))");
  });

  it("constrains both identities to secret-free references", () => {
    for (const id of ["identity_a", "identity_b"]) {
      expect(ddl).toContain(`check (${id}_kind is null or ${id}_kind in ('env', 'stored'))`);
      expect(ddl).toContain(`check (${id}_kind is distinct from 'env' or ${id}_ref ~ '^[a-z_][a-z0-9_]*$')`);
    }
  });

  it("keeps one live consent per target and only allows revocation", () => {
    expect(ddl).toContain(
      "create unique index if not exists idx_verification_target_probe_consents_live on verification_target_probe_consents (target_id) where revoked_at is null",
    );
    expect(ddl).toContain(
      "before update on verification_target_probe_consents for each row execute function verification_target_probe_consent_guard()",
    );
  });

  it("is tenant-consistent through composite keys", () => {
    expect(ddl).toContain("add constraint verification_target_id_tenant_key unique (id, tenant_id)");
    expect(ddl).toContain("references verification_target (id, tenant_id) on delete cascade");
    expect(ddl).toContain("references verification_run (id, tenant_id) on delete cascade");
  });

  it("writes reports once, caps the mock at observed and needs consent elsewhere", () => {
    expect(ddl).toContain("before update on security_probe_reports for each row execute function mcp_forbid_row_mutation()");
    expect(ddl).toContain("check (not hosted_mock or proof_ceiling = 'observed')");
    expect(ddl).toContain("check (hosted_mock or consent_id is not null)");
    expect(ddl).toContain("check (proof_ceiling = 'exploited-in-test' or count_exploited_in_test = 0)");
  });

  it("never uses on delete set null on a guarded row", () => {
    expect(ddl).not.toContain("on delete set null");
  });

  it("documents its rollback", () => {
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.security_probe_reports;");
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.verification_target_probe_consents;");
  });
});
