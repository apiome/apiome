/**
 * Structural assertions over the stale-pact remediation migration (#6954, PFX-6.2).
 *
 * V448 stores the workspace's Pact verification settings, provider-wide and per-pair overrides,
 * each pair's stale state, re-publish requests and scheduled verification attempts, and widens the
 * verification trigger and webhook event lists. DB-free contract tests pin its rules:
 *
 *   1. **Closed lists**: cadences, request states and attempt statuses.
 *   2. **Bounded numbers**: threshold 1 h … 90 days, 1 … 10 concurrent runs, window 1 h … 30 days.
 *   3. **One override per provider and per pair; one open request per pair.**
 *   4. **Nothing crosses a tenant**: every pacticipant / target reference is composite.
 *   5. **The widened lists** keep every earlier value.
 *
 * These must stay in lock-step with apiome-rest's `app.pact_remediation`, `app.pact_webhook.EVENT_NAMES`
 * and `app.verification_result.TRIGGERS`; `apiome-rest/tests/test_pact_remediation_db.py` proves the
 * same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V448__pact_stale_remediation_6954.sql";

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("stale-pact remediation migration (PFX-6.2)", () => {
  it("is present and ordered after the verification operations and tenant isolation", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V444__pact_verification_ops_6949.sql"));
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V447__pact_tenant_isolation_6953.sql"));
  });

  it("sets its own search path before creating anything", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBe(ddl.indexOf("set search_path"));
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("create table"));
  });

  it("creates the five tables idempotently", () => {
    for (const table of [
      "pact_verification_settings",
      "pact_verification_override",
      "pact_staleness",
      "pact_republish_request",
      "pact_scheduled_verification",
    ]) {
      expect(ddl).toContain(`create table if not exists ${table} (`);
    }
  });

  it("keeps the cadences, request states and attempt statuses to closed lists", () => {
    expect(ddl).toContain("check (cadence in ('on-publish', 'hourly', 'nightly', 'manual-only'))");
    expect(ddl).toContain(
      "check (cadence is null or cadence in ('on-publish', 'hourly', 'nightly', 'manual-only'))",
    );
    expect(ddl).toContain("check (state in ('requested', 'acknowledged', 'republished', 'cleared', 'expired'))");
    expect(ddl).toContain("check (status in ('verified', 'failed', 'skipped', 'errored'))");
  });

  it("bounds the numbers and defaults to a manual, 72-hour workspace", () => {
    expect(ddl).toContain("check (stale_threshold_hours between 1 and 2160)");
    expect(ddl).toContain("check (max_concurrent_runs between 1 and 10)");
    expect(ddl).toContain("check (request_window_hours between 1 and 720)");
    expect(ddl).toContain("cadence varchar(16) not null default 'manual-only'");
    expect(ddl).toContain("stale_threshold_hours integer not null default 72");
  });

  it("allows one override per provider, one per pair, and one open request per pair", () => {
    expect(ddl).toContain(
      "create unique index if not exists uq_pact_verification_override_provider on pact_verification_override (tenant_id, provider_id) where consumer_id is null",
    );
    expect(ddl).toContain(
      "create unique index if not exists uq_pact_verification_override_pair on pact_verification_override (tenant_id, provider_id, consumer_id) where consumer_id is not null",
    );
    expect(ddl).toContain(
      "create unique index if not exists uq_pact_republish_request_open on pact_republish_request (tenant_id, provider_id, consumer_id) where state in ('requested', 'acknowledged')",
    );
    expect(ddl).toContain(
      "check (cadence is not null or stale_threshold_hours is not null or target_id is not null)",
    );
  });

  it("references pacticipants and targets only by (id, tenant_id)", () => {
    expect(ddl).not.toMatch(/references pacticipant ?\(id\)/);
    expect(ddl).toContain("foreign key (provider_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade");
    expect(ddl).toContain("foreign key (consumer_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade");
    expect(ddl).toContain(
      "foreign key (target_id, tenant_id) references verification_target (id, tenant_id) on delete set null (target_id)",
    );
  });

  it("widens the trigger and webhook event lists without dropping a value", () => {
    expect(ddl).toContain(
      "trigger in ('published', 'hosted', 'manual', 'stale-recheck', 'bidirectional', 'scheduled')",
    );
    for (const event of [
      "contract_published",
      "contract_content_changed",
      "contract_requiring_verification_published",
      "provider_verification_published",
      "provider_verification_succeeded",
      "provider_verification_failed",
      "consumer_version_branch_created",
      "contract_became_stale",
      "contract_no_longer_stale",
      "contract_republish_requested",
      "contract_republish_request_expired",
    ]) {
      expect(ddl).toContain(`'${event}'`);
    }
  });
});
