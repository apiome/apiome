/**
 * Structural assertions over the auto-regen migration (#4497, SDK-4.3).
 *
 * V258 adds `apiome.sdk_regen_subscriptions`, `apiome.sdk_regen_runs` and `apiome.sdk_regen_jobs`.
 * SDK-4.1 (V256) publishes an SDK and SDK-4.2 (V257) delivers one as a pull request, but only when
 * someone asks; this migration is the durable half of watch mode — a subscription says which SDKs
 * regenerate on publish, and every publish expands it into jobs a worker runs.
 *
 * DB-free contract tests pin the migration shape, concentrating on the six rules that turn the
 * ticket's acceptance criteria into schema rather than habit:
 *
 *   1. **One subscription per project per ecosystem**, carrying a delivery mode and options.
 *   2. **A run is the publish event; a job is one cell of its matrix** — one job per ecosystem.
 *   3. **A job carries its own queue state**, including `retrying` and `dead_letter`.
 *   4. **One subscription's failure never blocks another's** — the claim is indexed per status and
 *      per subscription, so no ordering rule spans subscriptions.
 *   5. **The job links the event to what it produced** — the SDK-4.1 publish run and the SDK-4.2
 *      delivery run, plus the package version and pull request copied onto the job.
 *   6. **Unsubscribing stops future runs and touches nothing past** — `ON DELETE SET NULL`.
 *
 * There is deliberately **no new RBAC resource** and **no credential column**: a job authenticates
 * exactly as a manual publish or delivery does.
 *
 * These must stay in lock-step with apiome-rest's `app.sdk_regen_policy` /
 * `app.sdk_regen_subscriptions` contracts and their `tests/test_sdk_regen_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V258__sdk_regen_on_publish_4497.sql";
const SUBSCRIPTIONS = "sdk_regen_subscriptions";
const RUNS = "sdk_regen_runs";
const JOBS = "sdk_regen_jobs";

let sql = "";
let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** The statements of one table's CREATE block (up to the next CREATE TABLE). */
function tableSection(table: string): string {
  const start = statements.indexOf(`create table if not exists ${table} (`);
  const next = statements.indexOf("create table if not exists", start + 1);
  return statements.slice(start, next === -1 ? undefined : next);
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  statements = lower
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("sdk regen on publish migration", () => {
  it("is present in scripts/ and ordered after both ledgers it references", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V256__sdk_package_publishing_4495.sql"),
    );
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V257__sdk_git_delivery_4496.sql"),
    );
  });

  it("targets the apiome schema and creates all three tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    for (const table of [SUBSCRIPTIONS, RUNS, JOBS]) {
      expect(lower).toMatch(new RegExp(`create table if not exists ${table} \\(`));
    }
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — one subscription per project per ecosystem", () => {
    it("enforces it with a unique index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${SUBSCRIPTIONS}_project`);
      expect(lower).toContain(`on ${SUBSCRIPTIONS} (tenant_id, project_id, ecosystem)`);
    });

    it("carries a delivery mode, options and an enabled flag", () => {
      const section = tableSection(SUBSCRIPTIONS);
      expect(section).toContain("check (delivery_mode in ('registry', 'git', 'registry_and_git'))");
      expect(section).toContain("options jsonb not null default '{}'::jsonb");
      expect(section).toContain("active boolean not null default true");
      expect(section).not.toContain("'gomod'");
    });
  });

  describe("rule 2 — a run is the publish event; a job is one cell of its matrix", () => {
    it("allows one job per ecosystem per run, and keeps runs a log", () => {
      expect(lower).toContain(`create unique index if not exists idx_${JOBS}_run_ecosystem`);
      expect(lower).toContain(`on ${JOBS} (run_id, ecosystem)`);
      expect(statements.match(/create unique index/g) ?? []).toHaveLength(2);
      expect(tableSection(RUNS)).not.toContain("unique");
    });

    it("deletes a run's jobs with it", () => {
      expect(lower).toContain(`run_id uuid not null references ${RUNS}(id) on delete cascade`);
    });
  });

  describe("rule 3 — a job carries its own queue state", () => {
    it("constrains the lifecycle to the six states the worker writes", () => {
      expect(lower).toContain(
        "check (status in ('pending', 'running', 'retrying', 'succeeded', 'dead_letter', 'cancelled'))",
      );
    });

    it("records attempts, backoff, the claim and why an attempt failed", () => {
      const section = tableSection(JOBS);
      for (const column of [
        "attempt_count integer not null default 0",
        "next_attempt_at timestamptz",
        "claimed_at timestamptz",
        "claim_token uuid",
        "error_code varchar(64)",
        "error_message text",
        "attempts jsonb not null default '[]'::jsonb",
        "retry_requested_at timestamptz",
      ]) {
        expect(section).toContain(column);
      }
      expect(section).toContain(
        "check (error_step is null or error_step in ('generate', 'registry', 'git', 'worker'))",
      );
    });
  });

  describe("rule 4 — no ordering rule spans subscriptions", () => {
    it("indexes the claim, the per-subscription order, the lease and the dead letter", () => {
      expect(lower).toContain(`create index if not exists idx_${JOBS}_due`);
      expect(lower).toContain(`create index if not exists idx_${JOBS}_subscription_active`);
      expect(lower).toContain(`on ${JOBS} (subscription_id, created_at)`);
      expect(lower).toContain(`create index if not exists idx_${JOBS}_running`);
      expect(lower).toContain(`create index if not exists idx_${JOBS}_dead_letter`);
    });
  });

  describe("rule 5 — the job links the event to what it produced", () => {
    it("references the SDK-4.1 and SDK-4.2 run ledgers", () => {
      expect(lower).toContain("publish_run_id uuid references sdk_publish_runs(id) on delete set null");
      expect(lower).toContain(
        "delivery_run_id uuid references sdk_git_delivery_runs(id) on delete set null",
      );
    });

    it("copies the package and pull request coordinates onto the job", () => {
      const section = tableSection(JOBS);
      for (const column of [
        "package_name text",
        "package_version varchar(128)",
        "artifact_sha256 varchar(71)",
        "pull_request_number integer",
        "pull_request_url text",
      ]) {
        expect(section).toContain(column);
      }
    });
  });

  describe("rule 6 — unsubscribing touches nothing past", () => {
    it("sets a job's subscription and a run's version to NULL when they are deleted", () => {
      expect(lower).toContain(
        `subscription_id uuid references ${SUBSCRIPTIONS}(id) on delete set null`,
      );
      expect(lower).toContain("version_id uuid references versions(id) on delete set null");
    });

    it("cascades from the tenant and the project", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(lower).toContain("project_id uuid not null references projects(id) on delete cascade");
    });
  });

  describe("no new RBAC resource and no credential", () => {
    it("leaves seed_builtin_roles and the permission tables alone", () => {
      expect(statements).not.toContain("seed_builtin_roles");
      expect(statements).not.toContain("insert into apiome.role_permissions");
      expect(statements).not.toContain("insert into apiome.permissions");
    });

    it("opens no column a token or secret could be written to", () => {
      for (const column of [
        "access_token",
        "encrypted_token",
        "token text",
        "token bytea",
        "secret text",
        "secret bytea",
      ]) {
        expect(statements).not.toContain(column);
      }
    });
  });

  describe("documentation", () => {
    it("comments the tables and the columns a reader would otherwise misread", () => {
      for (const table of [SUBSCRIPTIONS, RUNS, JOBS]) {
        expect(lower).toContain(`comment on table ${table} is`);
      }
      expect(lower).toContain(`comment on column ${SUBSCRIPTIONS}.delivery_mode is`);
      expect(lower).toContain(`comment on column ${JOBS}.status is`);
      expect(lower).toContain(`comment on column ${JOBS}.claim_token is`);
    });

    it("carries rollback notes, like every other migration in this family", () => {
      expect(lower).toContain("rollback notes");
      for (const table of [JOBS, RUNS, SUBSCRIPTIONS]) {
        expect(lower).toContain(`drop table if exists apiome.${table}`);
      }
    });
  });
});
