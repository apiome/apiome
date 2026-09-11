/**
 * Structural assertions over the git delivery migration (#4496, SDK-4.2).
 *
 * V257 adds `apiome.sdk_git_delivery_targets` and `apiome.sdk_git_delivery_runs`. Registry
 * publishing (SDK-4.1, V256) serves an SDK's consumers; git delivery serves its owners — the
 * regenerated SDK arrives as a pull request against the tenant's own repository — and doing that
 * needs two durable things nothing else holds: where each SDK goes, and the record of every
 * attempt to send it there.
 *
 * DB-free contract tests pin the migration shape, concentrating on the five rules the ticket's
 * acceptance criteria turn into schema rules rather than habits:
 *
 *   1. **No new credential store.** A target references a registered repository and a delivery
 *      authenticates with that repository's existing linked-account integration — so there is no
 *      column anywhere in this migration a token could be written to.
 *   2. **One destination per project per ecosystem**, enforced by a unique index.
 *   3. **The target path is stored normalised** — CHECKs refuse a path that climbs out of the
 *      repository or into its `.git` directory, even from a hand-edited row.
 *   4. **Failures are runs.** `failed` is a status with an `error_code` and a redacted `log`, which
 *      is "credential failures and push rejections surface as failed jobs with actionable logs".
 *   5. **A run outlives its version, its target and its repository, but not its project.**
 *
 * There is deliberately **no new RBAC resource**: configuring a target is `projects:edit` (plus
 * `imports:edit`, which governs repositories) and delivering is `versions:publish`.
 *
 * These must stay in lock-step with apiome-rest's `app.sdk_git_delivery_targets` /
 * `app.sdk_git_delivery_pipeline` contracts and their `tests/test_sdk_git_delivery_migration.py`
 * sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V257__sdk_git_delivery_4496.sql";
const TARGETS = "sdk_git_delivery_targets";
const RUNS = "sdk_git_delivery_runs";

let sql = "";
let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  statements = lower
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("sdk git delivery migration", () => {
  it("is present in scripts/ and ordered after the publishing ledger it reads", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V256__sdk_package_publishing_4495.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(new RegExp(`create table if not exists ${TARGETS} \\(`));
    expect(lower).toMatch(new RegExp(`create table if not exists ${RUNS} \\(`));
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — no new credential store", () => {
    it("points a target at a registered repository", () => {
      expect(lower).toContain(
        "repository_id uuid not null references tenant_repositories(id) on delete cascade",
      );
    });

    it("opens no column a token or secret could be written to", () => {
      for (const column of [
        "token text",
        "token varchar",
        "token bytea",
        "access_token",
        "encrypted_token",
        "secret text",
        "secret bytea",
      ]) {
        expect(statements).not.toContain(column);
      }
    });
  });

  describe("rule 2 — one destination per project per ecosystem", () => {
    it("enforces it with the migration's only unique index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${TARGETS}_project`);
      expect(lower).toContain(`on ${TARGETS} (tenant_id, project_id, ecosystem)`);
      expect(statements.match(/create unique index/g) ?? []).toHaveLength(1);
    });

    it("constrains the ecosystem to the SDK-4.1 package layouts", () => {
      expect(lower).toContain("check (ecosystem in ('npm', 'pypi'))");
      expect(statements).not.toContain("'gomod'");
    });

    it("stores no default branch of its own — NULL means the repository's", () => {
      expect(lower).toContain("base_branch varchar(255)");
      expect(lower).not.toMatch(/base_branch varchar\(255\) not null/);
    });
  });

  describe("rule 3 — the target path cannot leave the repository", () => {
    it("defaults to the repository root", () => {
      expect(lower).toContain("target_path text not null default ''");
    });

    it("refuses leading/trailing slashes, dot segments, .git and backslashes", () => {
      expect(sql).toContain("target_path !~ '^/'");
      expect(sql).toContain("target_path !~ '/$'");
      expect(sql).toContain("target_path !~ '(^|/)\\.\\.?(/|$)'");
      expect(sql).toContain("target_path !~ '(^|/)\\.git(/|$)'");
      expect(sql).toContain("target_path !~ '//'");
    });
  });

  describe("rule 4 — failures are runs", () => {
    it("constrains the lifecycle to the six states the pipeline writes", () => {
      expect(lower).toContain(
        "check (status in ('in_progress', 'opened', 'updated', 'unchanged', 'up_to_date', 'failed'))",
      );
    });

    it("records why a run failed and what it did", () => {
      expect(lower).toContain("error_code varchar(64)");
      expect(lower).toContain("error_message text");
      expect(lower).toContain("log jsonb not null default '[]'::jsonb");
      expect(lower).toContain("check (jsonb_typeof(log) = 'array')");
      expect(lower).toContain("changes jsonb not null default '{}'::jsonb");
      expect(lower).toContain("provenance jsonb not null default '{}'::jsonb");
    });

    it("keeps runs a log: no uniqueness rule on them at all", () => {
      const runsSection = statements.slice(statements.indexOf(`create table if not exists ${RUNS}`));
      expect(runsSection).not.toContain("unique");
    });

    it("claims no version number (a pull request is not a release)", () => {
      const runsSection = statements.slice(statements.indexOf(`create table if not exists ${RUNS}`));
      expect(runsSection).not.toContain("_claim");
    });

    it("indexes the history listing and the branch lookup", () => {
      expect(lower).toContain(`create index if not exists idx_${RUNS}_history`);
      expect(lower).toContain(`create index if not exists idx_${RUNS}_branch`);
    });
  });

  describe("rule 5 — a run outlives what it points at, but not its project", () => {
    it("sets its version, target and repository to NULL when they are deleted", () => {
      expect(lower).toContain("version_id uuid references versions(id) on delete set null");
      expect(lower).toContain(`target_id uuid references ${TARGETS}(id) on delete set null`);
      expect(lower).toContain(
        "repository_id uuid references tenant_repositories(id) on delete set null",
      );
    });

    it("copies the coordinates that matter onto the run", () => {
      for (const column of [
        "repository_full_name varchar(512)",
        "branch_name varchar(255)",
        "commit_sha varchar(64)",
        "pull_request_number integer",
        "pull_request_url text",
      ]) {
        expect(lower).toContain(column);
      }
    });

    it("cascades from the tenant and the project", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(lower).toContain("project_id uuid not null references projects(id) on delete cascade");
    });
  });

  describe("no new RBAC resource", () => {
    it("leaves seed_builtin_roles and the permission tables alone", () => {
      expect(statements).not.toContain("seed_builtin_roles");
      expect(statements).not.toContain("insert into apiome.role_permissions");
      expect(statements).not.toContain("insert into apiome.permissions");
    });
  });

  describe("documentation", () => {
    it("comments both tables and the columns a reader would otherwise misread", () => {
      expect(lower).toContain(`comment on table ${TARGETS} is`);
      expect(lower).toContain(`comment on table ${RUNS} is`);
      expect(lower).toContain(`comment on column ${TARGETS}.base_branch is`);
      expect(lower).toContain(`comment on column ${TARGETS}.target_path is`);
      expect(lower).toContain(`comment on column ${RUNS}.status is`);
    });

    it("carries rollback notes, like every other migration in this family", () => {
      expect(lower).toContain("rollback notes");
      expect(lower).toContain(`drop table if exists apiome.${RUNS}`);
      expect(lower).toContain(`drop table if exists apiome.${TARGETS}`);
    });
  });
});
