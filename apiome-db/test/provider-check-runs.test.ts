/**
 * Structural assertions over the provider check migration (#4738, GNC-2.2).
 *
 * V265 adds `apiome.provider_check_runs` — one normalized API check verdict per (binding, commit,
 * check name), in a four-word vocabulary that belongs to the platform rather than to any provider
 * — and `apiome.provider_check_deliveries`, the append-only record of every attempt to put one of
 * those verdicts on a pull request. GNC-2.1 (V264) supplies the binding a check hangs off;
 * GNC-3.1 supplies the suite that produces the verdicts.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's
 * acceptance criteria turn into schema rather than habit:
 *
 *   1. **Four states, provider-independent** — `pending | pass | fail | skipped`, with
 *      `completed_at` tied to them so the two can never disagree.
 *   2. **A check is identified by what it is about** — unique on (binding, commit, name), which is
 *      what makes a re-run idempotent.
 *   3. **A check inherits its binding's authorization** — it hangs off the binding and dies with
 *      it; there is no independent path from a check to a repository.
 *   4. **Publishing is evidence** — append-only, one row per distinct verdict published.
 *   5. **No credential is stored, anywhere** — not even encrypted, because these rows are read
 *      straight into an API response a browser client receives.
 *
 * There is deliberately **no RBAC change**: recording a check needs `versions:edit` plus an active
 * binding, which apiome-rest enforces. These must stay in lock-step with apiome-rest's
 * `app.provider_checks` vocabulary and its `tests/test_provider_check_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V265__provider_check_runs_gnc_2_2.sql";
const CHECKS = "provider_check_runs";
const DELIVERIES = "provider_check_deliveries";

/** The four normalized states, in the order the migration lists them. */
const CHECK_STATES = ["pending", "pass", "fail", "skipped"];

/** How a check can come to exist. */
const CHECK_ORIGINS = ["webhook", "api", "sweep"];

/** What one publish attempt can have done. */
const PUBLISH_OUTCOMES = ["dispatched", "suppressed", "failed"];

/** The providers with a status adapter. */
const PROVIDERS = ["github", "gitlab", "bitbucket"];

/** Words that must never name a column of either table (rule 5). */
const CREDENTIAL_WORDS = ["token", "secret", "credential", "ciphertext", "password"];

let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** The table's column block: from its CREATE TABLE to the closing `);`. */
function tableBlock(table: string): string {
  const start = statements.indexOf(`create table if not exists ${table} (`);
  const end = statements.indexOf("\n);", start);
  return statements.slice(start, end);
}

/** One trigger function's body: from its CREATE FUNCTION to its `$$ language plpgsql`. */
function functionBody(name: string): string {
  const start = statements.indexOf(`create or replace function apiome.${name}()`);
  const end = statements.indexOf("$$ language plpgsql", start);
  return statements.slice(start, end);
}

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  statements = lower
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("provider check runs migration", () => {
  it("is present in scripts/ and ordered after the binding migration it builds on", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V264__draft_repository_bindings_gnc_2_1.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(statements).toMatch(new RegExp(`create table if not exists ${CHECKS} \\(`));
    expect(statements).toMatch(new RegExp(`create table if not exists ${DELIVERIES} \\(`));
  });

  // -- Rule 1 ---------------------------------------------------------------------------------

  it("stores exactly the four normalized states and nothing else", () => {
    const block = tableBlock(CHECKS);
    expect(block).toContain("state varchar(16) not null default 'pending'");
    expect(block).toContain(`check (state in (${CHECK_STATES.map((s) => `'${s}'`).join(", ")}))`);
    // Nothing a provider spells its own way leaks into the stored vocabulary.
    for (const foreign of ["in_progress", "success", "failure", "successful", "canceled"]) {
      expect(block).not.toContain(`'${foreign}'`);
    }
  });

  it("ties the completion time to the state so the two cannot disagree", () => {
    expect(tableBlock(CHECKS)).toContain(
      "check ((state = 'pending') = (completed_at is null))",
    );
  });

  it("records how a check came to exist", () => {
    const block = tableBlock(CHECKS);
    expect(block).toContain(`check (origin in (${CHECK_ORIGINS.map((o) => `'${o}'`).join(", ")}))`);
    expect(block).toContain("delivery_id varchar(255)");
  });

  // -- Rule 2 ---------------------------------------------------------------------------------

  it("identifies a check by its binding, its commit and its name", () => {
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_provider_check_runs_identity\\s+on ${CHECKS} \\(binding_id, commit_sha, name\\)`,
      ),
    );
    const block = tableBlock(CHECKS);
    expect(block).toContain("commit_sha varchar(64) not null");
    expect(block).toContain("name varchar(128) not null");
  });

  it("counts re-runs on the row rather than fanning out a second verdict", () => {
    expect(tableBlock(CHECKS)).toContain("attempt integer not null default 1");
    expect(functionBody("provider_check_runs_guard_identity")).toContain(
      "if new.attempt < old.attempt then",
    );
  });

  // -- Rule 3 ---------------------------------------------------------------------------------

  it("hangs a check off its binding and removes it with the binding", () => {
    const block = tableBlock(CHECKS);
    expect(block).toContain(
      "binding_id uuid not null references draft_repository_bindings(id) on delete cascade",
    );
    expect(block).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(block).toContain("project_id uuid not null references projects(id) on delete cascade");
    expect(block).toContain("version_id uuid not null references versions(id) on delete cascade");
    // The recorder may be deleted; the verdict they recorded survives them.
    expect(block).toContain("created_by uuid references users(id) on delete set null");
  });

  it("names the provider coordinates a verdict is published against", () => {
    const block = tableBlock(CHECKS);
    expect(block).toContain("provider varchar(32) not null");
    for (const provider of PROVIDERS) {
      expect(block).toContain(`'${provider}'`);
    }
    expect(block).toContain("repo_full_name varchar(512) not null");
    expect(statements).not.toContain("create type");
  });

  it("indexes the reads a reviewer and a merge gate make", () => {
    for (const [index, columns] of [
      ["idx_provider_check_runs_version_created", "\\(version_id, created_at desc\\)"],
      ["idx_provider_check_runs_binding_created", "\\(binding_id, created_at desc\\)"],
      ["idx_provider_check_runs_repo_commit", "\\(repo_full_name, commit_sha\\)"],
    ]) {
      expect(statements).toMatch(
        new RegExp(`create index if not exists ${index}\\s+on ${CHECKS} ${columns}`),
      );
    }
  });

  // -- Rule 4 ---------------------------------------------------------------------------------

  it("publishes one row per distinct verdict, keyed on the request fingerprint", () => {
    const block = tableBlock(DELIVERIES);
    expect(block).toContain("request_fingerprint varchar(128) not null");
    expect(block).toContain(
      `check (outcome in (${PUBLISH_OUTCOMES.map((o) => `'${o}'`).join(", ")}))`,
    );
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_provider_check_deliveries_fingerprint\\s+on ${DELIVERIES} \\(check_run_id, request_fingerprint\\)`,
      ),
    );
  });

  it("forbids an attempt claiming a reach it did not have", () => {
    // The V187 edge_attached / V197 dispatch_enabled discipline: a control plane that overstates
    // its reach is worse than one that admits its edge.
    const block = tableBlock(DELIVERIES);
    expect(block).toContain(
      "check (outcome <> 'suppressed' or (status_code is null and external_id is null))",
    );
    expect(block).toContain("check (outcome <> 'dispatched' or status_code is not null)");
  });

  it("refuses a rewrite of the ledger without taking the cascades hostage", () => {
    expect(statements).toMatch(
      new RegExp(
        `create trigger trg_provider_check_deliveries_append_only\\s+before update on ${DELIVERIES}\\s+for each row\\s+execute function apiome\\.provider_check_deliveries_append_only\\(\\)`,
      ),
    );
    // A BEFORE DELETE guard fires for the rows a cascade removes too, which would make deleting a
    // tenant, a project, a version, a binding or a check impossible.
    expect(statements).not.toContain(`delete on ${DELIVERIES}`);
    expect(statements).not.toMatch(new RegExp(`delete from apiome\\.${CHECKS}`));
  });

  // -- Rule 5 ---------------------------------------------------------------------------------

  it("gives a credential nowhere to sit on either table", () => {
    for (const table of [CHECKS, DELIVERIES]) {
      const block = tableBlock(table);
      for (const word of CREDENTIAL_WORDS) {
        expect(block, `${table} must not name a column ${word}`).not.toContain(word);
      }
    }
  });

  // -- Identity -------------------------------------------------------------------------------

  it("freezes what a check is about while letting its verdict move", () => {
    const guard = functionBody("provider_check_runs_guard_identity");
    for (const column of [
      "tenant_id",
      "binding_id",
      "project_id",
      "version_id",
      "provider",
      "repo_full_name",
      "commit_sha",
      "name",
      "created_at",
    ]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    // The verdict and how it reads are exactly what an update is for.
    for (const column of ["state", "title", "summary", "details_url", "external_id"]) {
      expect(guard).not.toContain(`new.${column} is distinct from old.${column}`);
    }
    expect(statements).toMatch(
      new RegExp(
        `create trigger trg_provider_check_runs_guard_identity\\s+before update on ${CHECKS}\\s+for each row\\s+execute function apiome\\.provider_check_runs_guard_identity\\(\\)`,
      ),
    );
  });

  it("documents both tables and every column whose meaning is not obvious", () => {
    for (const table of [CHECKS, DELIVERIES]) {
      expect(statements).toContain(`comment on table ${table} is`);
    }
    for (const column of ["state", "commit_sha", "name", "attempt", "completed_at", "origin"]) {
      expect(statements).toContain(`comment on column ${CHECKS}.${column} is`);
    }
    for (const column of ["state", "request_fingerprint", "outcome", "error_message"]) {
      expect(statements).toContain(`comment on column ${DELIVERIES}.${column} is`);
    }
  });

  it("carries rollback notes for a shared environment", () => {
    expect(lower).toContain(`drop table if exists apiome.${DELIVERIES}`);
    expect(lower).toContain(`drop table if exists apiome.${CHECKS}`);
    expect(lower).toContain("drop function if exists apiome.provider_check_runs_guard_identity");
    expect(lower).toContain(
      "drop function if exists apiome.provider_check_deliveries_append_only",
    );
  });
});
