/**
 * Structural assertions over the package-publishing migration (#4495, SDK-4.1).
 *
 * V256 adds `apiome.sdk_registry_credentials` and `apiome.sdk_publish_runs`. Downloading a zip is
 * not how SDKs are consumed at scale — a team expects `npm install @acme/api` — and publishing on
 * a tenant's behalf needs two durable things nothing else holds: the credential that authorises
 * the upload, and the ledger that decides what version number the next upload claims.
 *
 * DB-free contract tests pin the migration shape, concentrating on the six rules the ticket's
 * acceptance criteria turn into schema rules rather than habits:
 *
 *   1. **The token is ciphertext, and only ciphertext.** `encrypted_token BYTEA` plus a
 *      `key_version` naming the master key that sealed it. "Credentials are stored encrypted" is a
 *      schema fact here, not only an application one: there is no column a plaintext token could
 *      be written to.
 *   2. **What can be *shown* about a token lives beside it, in the clear** — its public scheme
 *      prefix, its length and a truncated digest, in `token_metadata`. Enough to confirm a
 *      rotation; not enough to use.
 *   3. **Credentials override whole, settings merge by key.** Unlike V255's
 *      `sdk_generation_settings`, a project row *replaces* the tenant row for its ecosystem: half
 *      of one token and half of another is not a credential. Two partial unique indexes keep one
 *      row per (scope, ecosystem).
 *   4. **The regen counter is a consequence of the ledger.** The published version is
 *      `major.minor.<counter>`; `idx_sdk_publish_runs_claim` is what makes deriving the counter
 *      safe under concurrency, because two publishes that compute the same number cannot both
 *      insert.
 *   5. **A claim is made before the upload, not after.** `in_progress` holds a number while an
 *      upload is in flight; `failed` and `dry_run` sit outside every claim predicate, so a number
 *      nothing was published under is free again.
 *   6. **A run outlives its version, but not its project.** `version_id` is `ON DELETE SET NULL`
 *      — the record that a package was published from revision X must survive that revision being
 *      deleted, or the provenance embedded in a package on npm points at nothing.
 *
 * There is deliberately **no new RBAC resource**: managing a credential is `projects:edit` and
 * releasing a package is `versions:publish`.
 *
 * These must stay in lock-step with apiome-rest's `app.sdk_registry_credentials` /
 * `app.sdk_publish_pipeline` contracts and their
 * `tests/test_sdk_package_publishing_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V256__sdk_package_publishing_4495.sql";
const CREDENTIALS = "sdk_registry_credentials";
const RUNS = "sdk_publish_runs";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("sdk package publishing migration", () => {
  it("is present in scripts/ and ordered after the settings it names packages with", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V255__sdk_generation_settings_4494.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(new RegExp(`create table if not exists ${CREDENTIALS} \\(`));
    expect(lower).toMatch(new RegExp(`create table if not exists ${RUNS} \\(`));
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — the token is ciphertext, and only ciphertext", () => {
    it("stores it as BYTEA with the key version that sealed it", () => {
      expect(lower).toContain("encrypted_token bytea not null");
      expect(lower).toContain("key_version integer not null");
      expect(lower).toContain("check (key_version >= 1)");
    });

    it("opens no column a plaintext token could be written to", () => {
      for (const column of ["token text", "token varchar", "plaintext_token", "secret text"]) {
        expect(lower).not.toContain(column);
      }
    });
  });

  describe("rule 2 — describable, not readable", () => {
    it("keeps the non-secret description as a JSONB object with a shape check", () => {
      expect(lower).toContain("token_metadata jsonb not null default '{}'::jsonb");
      expect(lower).toContain(`constraint ${CREDENTIALS}_metadata_object_check`);
      expect(lower).toContain("check (jsonb_typeof(token_metadata) = 'object')");
    });
  });

  describe("rule 3 — two scopes, whole-row override, one row each per ecosystem", () => {
    it("constrains the ecosystem to the two that have an upload transport", () => {
      expect(lower).toContain("check (ecosystem in ('npm', 'pypi'))");
      // `gomod` names a module path; a Go module is released by a tag, not by an upload.
      expect(lower).not.toContain("'gomod'");
    });

    it("keeps one workspace credential per ecosystem, via a partial unique index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${CREDENTIALS}_tenant`);
      expect(lower).toMatch(
        new RegExp(`on ${CREDENTIALS} \\(tenant_id, ecosystem\\)\\s*\\n\\s*where project_id is null`),
      );
    });

    it("keeps one override per project per ecosystem, via the complementary index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${CREDENTIALS}_project`);
      expect(lower).toMatch(
        new RegExp(
          `on ${CREDENTIALS} \\(tenant_id, project_id, ecosystem\\)\\s*\\n\\s*where project_id is not null`,
        ),
      );
    });
  });

  describe("rules 4 and 5 — the claim is what makes the derived counter safe", () => {
    it("declares the claim as a partial unique index over the package version", () => {
      expect(lower).toContain(`create unique index if not exists idx_${RUNS}_claim`);
      expect(lower).toContain(
        `on ${RUNS} (tenant_id, project_id, ecosystem, package_version)`,
      );
    });

    it("covers exactly the statuses under which something may exist on the registry", () => {
      const predicates = sql
        .split("\n")
        .filter((line) => line.includes("WHERE status IN"));
      expect(predicates.length).toBeGreaterThanOrEqual(2);
      for (const predicate of predicates) {
        expect(predicate).toContain("'in_progress'");
        expect(predicate).toContain("'published'");
        expect(predicate).toContain("'already_published'");
        // A validation must not consume a number, and a failure must give one back.
        expect(predicate).not.toContain("'dry_run'");
        expect(predicate).not.toContain("'failed'");
      }
    });

    it("records the series and the counter the version was derived from", () => {
      expect(lower).toContain("release_series varchar(64) not null");
      expect(lower).toContain("regen_counter integer not null");
      expect(lower).toContain("check (regen_counter >= 0)");
      expect(lower).toContain("version_line text");
    });

    it("constrains the lifecycle to the five states the pipeline writes", () => {
      expect(lower).toContain(
        "check (status in ('in_progress', 'published', 'already_published', 'failed', 'dry_run'))",
      );
    });

    it("indexes the counter query and the history listing", () => {
      expect(lower).toContain(`create index if not exists idx_${RUNS}_series`);
      expect(lower).toContain(`create index if not exists idx_${RUNS}_history`);
    });

    it("declares no second uniqueness rule on runs that could block a legal claim", () => {
      const runsSection = sql.slice(sql.indexOf(`CREATE TABLE IF NOT EXISTS ${RUNS}`));
      expect(runsSection.match(/CREATE UNIQUE INDEX/g) ?? []).toHaveLength(1);
    });
  });

  describe("rule 6 — a run outlives its version, but not its project", () => {
    it("keeps the run when its revision is deleted", () => {
      expect(lower).toContain("version_id uuid references versions(id) on delete set null");
    });

    it("cascades from the tenant and the project", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(lower).toContain("project_id uuid not null references projects(id) on delete cascade");
    });

    it("keeps the provenance and the log as documents", () => {
      expect(lower).toContain("provenance jsonb not null default '{}'::jsonb");
      expect(lower).toContain("log jsonb not null default '[]'::jsonb");
      expect(lower).toContain("check (jsonb_typeof(log) = 'array')");
    });
  });

  describe("no new RBAC resource", () => {
    it("leaves seed_builtin_roles alone", () => {
      expect(lower).not.toContain("perform apiome.seed_builtin_roles");
      expect(lower).not.toContain("select apiome.seed_builtin_roles");
      expect(lower).not.toContain("create or replace function seed_builtin_roles");
    });

    it("touches no role or permission table", () => {
      expect(lower).not.toContain("insert into apiome.role_permissions");
      expect(lower).not.toContain("insert into apiome.permissions");
    });
  });

  describe("documentation", () => {
    it("comments both tables and the columns a reader would otherwise misread", () => {
      expect(lower).toContain(`comment on table ${CREDENTIALS} is`);
      expect(lower).toContain(`comment on table ${RUNS} is`);
      expect(lower).toContain(`comment on column ${CREDENTIALS}.encrypted_token is`);
      expect(lower).toContain(`comment on column ${RUNS}.release_series is`);
    });

    it("carries rollback notes, like every other migration in this family", () => {
      expect(lower).toContain("rollback notes");
      expect(lower).toContain(`drop table if exists apiome.${RUNS}`);
      expect(lower).toContain(`drop table if exists apiome.${CREDENTIALS}`);
    });
  });
});
