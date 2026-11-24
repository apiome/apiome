/**
 * Structural assertions over the pacticipant registry migration (#6914, PFX-1.1).
 *
 * V432 adds the model the Pact Broker surface is built on: pacticipants, their versions, branches
 * and tags. DB-free contract tests pin its rules:
 *
 *   1. **Names are unique per tenant.**
 *   2. **Nothing crosses a tenant**: only `pacticipant` carries `tenant_id`; bindings and child rows
 *      use composite keys.
 *   3. **Deleting a project keeps the pacticipant and clears the binding**, for a hard delete and
 *      for the `deleted_at` stamp the app writes. Retiring or deleting a consumer does the same.
 *   4. **Versions never mutate.**
 *   5. **A tag and a branch membership exist once.**
 *   6. **`pacts`**: view / create / edit for Editor, delete for Owner and Admin only.
 *
 * These must stay in lock-step with apiome-rest's `app.pacticipant` and `app.pacticipant_store`;
 * `apiome-rest/tests/test_pacticipant_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V432__pacticipant_registry_6914.sql";
const PREVIOUS_SEED = "V408__tenant_document_stores_7092.sql";

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** The body of `seed_builtin_roles` in a migration. */
function seedFunctionOf(sql: string): string {
  const start = sql.indexOf("CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles");
  return sql.slice(start, sql.indexOf("$$ LANGUAGE plpgsql;", start));
}

let ddl = "";
let raw = "";

beforeAll(async () => {
  raw = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = statementsOf(raw);
});

describe("pacticipant registry migration (PFX-1.1)", () => {
  it("is present in scripts/ and ordered after the browse directory migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V431__browse_public_projects_7210.sql"));
  });

  it("sets its own search path before using uuid_generate_v4()", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBeGreaterThan(-1);
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("uuid_generate_v4()"));
  });

  it("creates the five tables idempotently", () => {
    for (const table of [
      "pacticipant",
      "pacticipant_version",
      "pacticipant_branch",
      "pacticipant_branch_version",
      "pacticipant_version_tag",
    ]) {
      expect(ddl).toContain(`create table if not exists ${table} (`);
    }
  });

  it("keeps a pacticipant handle shaped and unique per tenant", () => {
    expect(ddl).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(ddl).toContain("check (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$')");
    expect(ddl).toContain("constraint pacticipant_tenant_slug_key unique (tenant_id, slug)");
  });

  it("carries tenant_id on the pacticipant only", () => {
    expect(ddl.match(/tenant_id uuid not null/g)).toHaveLength(1);
  });

  it("binds only to a project or consumer of the same tenant, and clears the binding on delete", () => {
    expect(ddl).toContain("add constraint projects_id_tenant_key unique (id, tenant_id)");
    expect(ddl).toContain("add constraint consumer_id_tenant_key unique (id, tenant_id)");
    expect(ddl).toContain(
      "foreign key (project_id, tenant_id) references projects (id, tenant_id) on delete set null (project_id)",
    );
    expect(ddl).toContain(
      "foreign key (consumer_id, tenant_id) references consumer (id, tenant_id) on delete set null (consumer_id)",
    );
    // Never a cascade from a project or a consumer into the registry.
    expect(ddl).not.toMatch(/references (projects|consumer) ?\([^)]*\) on delete cascade/);
  });

  it("clears the project binding when the app soft-deletes the project", () => {
    expect(ddl).toContain("after update of deleted_at on apiome.projects");
    expect(ddl).toContain("when (old.deleted_at is null and new.deleted_at is not null)");
    expect(ddl).toContain(
      "update apiome.pacticipant set project_id = null, updated_at = current_timestamp where project_id = new.id and tenant_id = new.tenant_id",
    );
  });

  it("clears the consumer binding when the consumer is retired", () => {
    expect(ddl).toContain("after update of deleted_at on apiome.consumer");
    expect(ddl).toContain(
      "update apiome.pacticipant set consumer_id = null, updated_at = current_timestamp where consumer_id = new.id and tenant_id = new.tenant_id",
    );
    expect(ddl.match(/when \(old\.deleted_at is null and new\.deleted_at is not null\)/g)).toHaveLength(2);
  });

  it("makes versions immutable and orders them by a sequence", () => {
    expect(ddl).toContain("constraint pacticipant_version_number_key unique (pacticipant_id, number)");
    expect(ddl).toContain("seq bigint generated always as identity");
    expect(ddl).toContain("before update on apiome.pacticipant_version for each row");
    expect(ddl).toContain("raise exception 'pacticipant_version rows are immutable");
    // The one change let through is the user FK being nulled.
    expect(ddl).toContain("(to_jsonb(new) - 'created_by') = (to_jsonb(old) - 'created_by')");
  });

  it("gives a branch one head, of its own pacticipant", () => {
    expect(ddl).toContain("constraint pacticipant_branch_name_key unique (pacticipant_id, name)");
    expect(ddl).toContain("head_version_id uuid not null");
    expect(ddl).toContain(
      "foreign key (head_version_id, pacticipant_id) references pacticipant_version (id, pacticipant_id)",
    );
  });

  it("stores a branch membership and a tag once, inside one pacticipant", () => {
    expect(ddl).toContain(
      "constraint pacticipant_branch_version_pkey primary key (branch_id, pacticipant_id, version_id)",
    );
    expect(ddl).toContain(
      "foreign key (branch_id, pacticipant_id) references pacticipant_branch (id, pacticipant_id) on delete cascade",
    );
    expect(ddl).toContain("constraint pacticipant_version_tag_pkey primary key (version_id, pacticipant_id, name)");
    expect(ddl.match(/references pacticipant_version \(id, pacticipant_id\) on delete cascade/g)).toHaveLength(2);
  });

  it("indexes every foreign key that does not reference users", () => {
    for (const index of [
      "on pacticipant (project_id, tenant_id) where project_id is not null",
      "on pacticipant (consumer_id, tenant_id) where consumer_id is not null",
      "on pacticipant_version (pacticipant_id, seq desc)",
      "on pacticipant_branch (head_version_id, pacticipant_id)",
      "on pacticipant_branch_version (version_id, pacticipant_id)",
      "on pacticipant_version_tag (pacticipant_id, name)",
    ]) {
      expect(ddl).toContain(index);
    }
  });

  it("adds pacts to every built-in grid, without delete for Editor", () => {
    expect(ddl).toContain("'consumer_contracts','teams','pacts']");
    expect(ddl).toContain("select v_editor, 'pacts', a from unnest(array['view','create','edit']) as a");
    expect(ddl).not.toContain("v_editor, 'pacts', a from unnest(array['view','create','edit','delete']");
    expect(ddl).toContain("perform apiome.seed_builtin_roles(t.id)");
  });

  it("carries every earlier grant of seed_builtin_roles forward", async () => {
    const previous = seedFunctionOf(await fs.readFile(path.join(SCRIPTS_DIR, PREVIOUS_SEED), "utf8"));
    const current = seedFunctionOf(raw);
    const inserts = (body: string) =>
      statementsOf(body)
        .split(";")
        .map((statement) => statement.trim())
        .filter((statement) => statement.startsWith("insert into apiome.role_permissions"));
    const carried = inserts(current);
    for (const statement of inserts(previous)) {
      expect(carried).toContain(statement);
    }
    expect(carried.length).toBe(inserts(previous).length + 1);
  });
});
