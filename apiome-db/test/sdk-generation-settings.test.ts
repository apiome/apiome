/**
 * Structural assertions over the SDK generation settings migration (#4494, SDK-3.4).
 *
 * V255 adds `apiome.sdk_generation_settings`. An organisation wants the code Apiome hands its
 * consumers to carry the organisation's identity — packages under its own npm scope / PyPI naming
 * pattern, its licence header, its user-agent — and none of that is a property of any version,
 * project row or generated file. It is tenant policy, and this table is its durable home.
 *
 * DB-free contract tests pin the migration shape, concentrating on the five rules the ticket's
 * acceptance criteria turn into schema rules rather than habits:
 *
 *   1. **Two scopes, one shape.** `project_id IS NULL` is the workspace default; a row naming a
 *      project overrides it. Two *partial* unique indexes keep exactly one row per scope, so "the
 *      settings in force" is a lookup rather than a reduction over history — and so the two
 *      `ON CONFLICT … WHERE …` upserts apiome-rest issues have an index to resolve against.
 *   2. **The override is per field, not per row.** Unlike CTG-4.5's `deploy_gate_policy`, whose
 *      project override replaces the whole threshold body, a project that overrides only its
 *      user-agent must still inherit its tenant's package pattern. apiome-rest reads *both* rows
 *      and merges them key by key, which is what makes rule 3 load-bearing.
 *   3. **"Unset" and "set to nothing" are different answers.** Every setting lives inside one JSONB
 *      body rather than as nullable columns: an absent key inherits the next scope up, an explicit
 *      `null` is deliberately none and blocks that inheritance, and only a document says both.
 *   4. **The row is mutable, deliberately** — the same argument CTG-4.5 made. These settings
 *      produce no stored verdict, so there is no past judgment for a version history to explain;
 *      attribution of a change lives in `access_audit`.
 *   5. **Settings cannot outlive their scope.** Both foreign keys cascade.
 *
 * There is deliberately **no new RBAC resource**: reading the settings in force is `projects:view`
 * and changing them is `projects:edit`.
 *
 * These must stay in lock-step with apiome-rest's `app.sdk_generation_settings` contract
 * (`SdkGenerationSettings`, `sdk.generation-settings.v1`) and its
 * `tests/test_sdk_generation_settings_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V255__sdk_generation_settings_4494.sql";
const TABLE = "sdk_generation_settings";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("sdk generation settings migration", () => {
  it("is present in scripts/ and ordered after the policy table it borrows its shape from", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V254__deploy_gate_policy_ctg_4_5.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(new RegExp(`create table if not exists ${TABLE} \\(`));
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — two scopes, one row each", () => {
    it("carries the tenant and an optional project", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(lower).toContain("project_id uuid references projects(id) on delete cascade");
    });

    it("keeps one workspace default, via a partial unique index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${TABLE}_tenant`);
      expect(lower).toMatch(
        new RegExp(`on ${TABLE} \\(tenant_id\\)\\s*\\n\\s*where project_id is null`),
      );
    });

    it("keeps one override per project, via the complementary partial index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${TABLE}_project`);
      expect(lower).toMatch(
        new RegExp(
          `on ${TABLE} \\(tenant_id, project_id\\)\\s*\\n\\s*where project_id is not null`,
        ),
      );
    });

    it("declares no third uniqueness rule that a NULL project would slip past", () => {
      expect(sql.match(/CREATE UNIQUE INDEX/g) ?? []).toHaveLength(2);
    });
  });

  describe("rules 2 and 3 — the settings are one document, not columns", () => {
    it("stores them as a JSONB object with a shape check", () => {
      expect(lower).toContain("settings jsonb not null default '{}'::jsonb");
      expect(lower).toContain(`constraint ${TABLE}_object_check`);
      expect(lower).toContain("check (jsonb_typeof(settings) = 'object')");
    });

    it("fingerprints the body so identical settings are demonstrably identical", () => {
      // 71 = "sha256:" + 64 hex characters, the same width every other fingerprint column uses.
      expect(lower).toContain("content_fingerprint varchar(71) not null");
    });

    it("names no individual setting as a column", () => {
      for (const setting of [
        "package_name_pattern",
        "license_header",
        "user_agent",
        "npm_scope",
      ]) {
        expect(lower).not.toContain(setting);
      }
    });
  });

  describe("rule 4 — the row is mutable, like CTG-4.5's and unlike the append-only policies", () => {
    it("installs no immutability trigger", () => {
      expect(lower).not.toContain(`before update on ${TABLE}`);
      expect(lower).not.toContain("mcp_forbid_row_mutation");
    });

    it("tracks when and by whom it last changed", () => {
      expect(lower).toContain("updated_at timestamptz not null default current_timestamp");
      expect(lower).toContain("updated_by uuid references users(id) on delete set null");
    });

    it("does not take a version number, because there is no history to reduce", () => {
      expect(lower).not.toContain("version_number");
    });
  });

  describe("rule 5 — settings cannot outlive their scope", () => {
    it("cascades from both the tenant and the project", () => {
      expect(sql.match(/ON DELETE CASCADE/g) ?? []).toHaveLength(2);
    });

    it("keeps provenance when a user is deleted rather than taking the branding with them", () => {
      expect(lower).toContain("created_by uuid references users(id) on delete set null");
      expect(lower).toContain("updated_by uuid references users(id) on delete set null");
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
      expect(lower).not.toContain("insert into role_permissions");
    });
  });

  it("adds exactly one table, and no other object", () => {
    expect(sql.match(/CREATE TABLE/g) ?? []).toHaveLength(1);
    expect(sql.match(/CREATE INDEX/g) ?? []).toHaveLength(0);
  });

  it("documents its rollback, like every migration that adds a table", () => {
    expect(lower).toContain(`drop table if exists apiome.${TABLE};`);
  });
});
