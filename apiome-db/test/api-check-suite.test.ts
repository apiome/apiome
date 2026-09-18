/**
 * Structural assertions over the API change check suite migration (#4740, GNC-3.1).
 *
 * V267 adds `apiome.api_check_suite_policy` — which suite components a tenant (or one project)
 * requires, and whether a passing suite is required to publish — and `apiome.api_check_suite_runs`,
 * one append-only row per distinct evaluation of a version. It also indexes ECA-1.3's
 * `verification_run` by the revision its suite was compiled from, and re-keys GNC-2.2's publish
 * ledger per outcome so a successful retry after a failed publish is recorded.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's acceptance
 * criteria turn into schema rather than habit:
 *
 *   1. **Deterministic, four-state verdicts** — `pending | pass | fail | skipped`, and a placeholder
 *      that judged nothing may never pass or fail.
 *   2. **Idempotent re-runs** — unique on (version, input fingerprint).
 *   3. **The drill-down names its evidence and policy** — components plus both policy snapshots.
 *   4. **Evaluations are evidence** — append-only, except the ON DELETE SET NULL of their author.
 *   5. **A dispatch after a failure lands** — the ledger is unique per verdict per outcome.
 *
 * There is deliberately **no RBAC change**. These must stay in lock-step with apiome-rest's
 * `app.api_check_suite` vocabulary and its `tests/test_api_check_suite_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V267__api_check_suite_gnc_3_1.sql";
const POLICY = "api_check_suite_policy";
const RUNS = "api_check_suite_runs";

/** The four normalized states, shared with GNC-2.2's check runs. */
const STATES = ["pending", "pass", "fail", "skipped"];

/** Where a policy came from. */
const SOURCES = ["default", "tenant", "project"];

/** Words that must never name a column of either table — a verdict holds no credential. */
const CREDENTIAL_WORDS = ["token", "secret", "credential", "ciphertext", "password"];

/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** The table's column block: from its CREATE TABLE to the closing `);`. */
function tableBlock(table: string): string {
  const start = statements.indexOf(`create table if not exists ${table} (`);
  const end = statements.indexOf("\n);", start);
  return statements.slice(start, end);
}

/** The quoted values of one `CHECK (column IN (...))` list. */
function checkValues(marker: string): string[] {
  const start = statements.indexOf(marker) + marker.length;
  const body = statements.slice(start, statements.indexOf("))", start));
  return body.split("'").filter((_, index) => index % 2 === 1);
}

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("API change check suite migration", () => {
  it("is present in scripts/ and ordered after the migrations it builds on", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    for (const earlier of [
      "V254__deploy_gate_policy_ctg_4_5.sql",
      "V265__provider_check_runs_gnc_2_2.sql",
      "V266__draft_sync_plans_gnc_2_3.sql",
    ]) {
      expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf(earlier));
    }
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain(`create table if not exists ${POLICY} (`);
    expect(statements).toContain(`create table if not exists ${RUNS} (`);
  });

  // -- Rule 1 ---------------------------------------------------------------------------------

  it("speaks exactly the four normalized states", () => {
    expect(checkValues("check (state in (")).toEqual(STATES);
  });

  it("forbids a placeholder that judged nothing from passing or failing", () => {
    const block = tableBlock(RUNS);
    expect(block).toContain("evaluated boolean not null");
    expect(block).toContain("check (evaluated or state in ('pending', 'skipped'))");
  });

  it("ties a reported commit to the binding it was reported through", () => {
    expect(tableBlock(RUNS)).toContain("check ((binding_id is null) = (commit_sha is null))");
  });

  // -- Rule 2 ---------------------------------------------------------------------------------

  it("identifies an evaluation by what it judged", () => {
    expect(statements).toContain("create unique index if not exists uq_api_check_suite_runs_input");
    expect(statements).toContain("on api_check_suite_runs (version_id, input_fingerprint)");
  });

  // -- Rule 3 ---------------------------------------------------------------------------------

  it("snapshots both policies an evaluation was judged under", () => {
    const block = tableBlock(RUNS);
    for (const column of [
      "policy_fingerprint varchar(71) not null",
      "thresholds_fingerprint varchar(71) not null",
      "draft_digest varchar(71) not null",
    ]) {
      expect(block).toContain(column);
    }
    expect(checkValues("check (policy_source in (")).toEqual(SOURCES);
    expect(checkValues("check (thresholds_source in (")).toEqual(SOURCES);
    expect(block).toContain("check (jsonb_typeof(components) = 'array')");
  });

  it("keeps one policy per scope", () => {
    expect(statements).toMatch(/on api_check_suite_policy \(tenant_id\)\s+where project_id is null/);
    expect(statements).toMatch(
      /on api_check_suite_policy \(tenant_id, project_id\)\s+where project_id is not null/,
    );
  });

  // -- Rule 4 ---------------------------------------------------------------------------------

  it("appends evaluations and allows only the author's SET NULL", () => {
    expect(statements).toContain("before update on api_check_suite_runs");
    expect(statements).toContain("(to_jsonb(new) - 'created_by') = (to_jsonb(old) - 'created_by')");
    // A BEFORE DELETE guard would also block every cascade that removes a project or a tenant.
    expect(statements).not.toContain("delete on api_check_suite_runs");
  });

  it("gives neither table anywhere to put a credential", () => {
    for (const table of [POLICY, RUNS]) {
      const block = tableBlock(table);
      for (const word of CREDENTIAL_WORDS) {
        expect(block).not.toContain(word);
      }
    }
  });

  it("touches no RBAC grid", () => {
    expect(statements).not.toContain("seed_builtin_roles");
    expect(statements).not.toContain("role_permissions");
  });

  // -- Rule 5 and the evidence index ------------------------------------------------------------

  it("re-keys the publish ledger per outcome without a moment of no uniqueness", () => {
    const created = statements.indexOf(
      "create unique index if not exists uq_provider_check_deliveries_fingerprint_outcome",
    );
    const dropped = statements.indexOf("drop index if exists uq_provider_check_deliveries_fingerprint;");
    expect(created).toBeGreaterThan(-1);
    expect(dropped).toBeGreaterThan(created);
    expect(statements).toContain(
      "on provider_check_deliveries (check_run_id, request_fingerprint, outcome)",
    );
  });

  it("indexes contract runs by the revision their suite was compiled from", () => {
    expect(statements).toContain(
      "on verification_run (tenant_id, (source ->> 'revision_id'), created_at desc)",
    );
    expect(statements).toContain("where source ? 'revision_id'");
  });
});
