/**
 * Structural assertions over the pact publication migration (#6915, PFX-1.2).
 *
 * V433 stores the pacts consumers publish. DB-free contract tests pin its rules:
 *
 *   1. **Content is stored once**: a pact version is unique per consumer, provider and SHA-256.
 *   2. **One pact per consumer version and provider.**
 *   3. **Nothing crosses a tenant**: both pacticipants are referenced by `(id, tenant_id)`, and a
 *      publication joins a version and a pact of the same pair only.
 *   4. **A pact goes with its pacticipants** (every reference cascades).
 *
 * These must stay in lock-step with apiome-rest's `app.pact_publication_store`;
 * `apiome-rest/tests/test_pact_publication_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V433__pact_publication_6915.sql";

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

describe("pact publication migration (PFX-1.2)", () => {
  it("is present in scripts/ and ordered after the pacticipant registry", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V432__pacticipant_registry_6914.sql"));
  });

  it("sets its own search path before using uuid_generate_v4()", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBeGreaterThan(-1);
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("uuid_generate_v4()"));
  });

  it("creates the two tables idempotently", () => {
    expect(ddl).toContain("create table if not exists pact_version (");
    expect(ddl).toContain("create table if not exists pact_publication (");
  });

  it("stores a pact once per consumer, provider and content hash", () => {
    expect(ddl).toContain("check (sha ~ '^[0-9a-f]{64}$')");
    expect(ddl).toContain("content jsonb not null");
    expect(ddl).toContain("check (jsonb_typeof(content) = 'object')");
    expect(ddl).toContain("constraint pact_version_content_key unique (consumer_id, provider_id, sha)");
  });

  it("keeps one pact per consumer version and provider, and counts replacements", () => {
    expect(ddl).toContain(
      "constraint pact_publication_version_provider_key unique (consumer_version_id, consumer_id, provider_id)",
    );
    expect(ddl).toContain("revision integer not null default 1");
    expect(ddl).toContain("check (revision >= 1)");
  });

  it("references both pacticipants inside one tenant", () => {
    expect(ddl).toContain("add constraint pacticipant_id_tenant_key unique (id, tenant_id)");
    expect(ddl).toContain(
      "foreign key (consumer_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (provider_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade",
    );
  });

  it("joins a publication to a version and a pact of the same pair, cascading both", () => {
    expect(ddl).toContain("constraint pact_version_id_pair_key unique (id, consumer_id, provider_id)");
    expect(ddl).toContain(
      "foreign key (consumer_version_id, consumer_id) references pacticipant_version (id, pacticipant_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (pact_version_id, consumer_id, provider_id) references pact_version (id, consumer_id, provider_id) on delete cascade",
    );
  });

  it("indexes every foreign key that does not reference users", () => {
    for (const index of [
      "on pact_version (consumer_id, tenant_id)",
      "on pact_version (provider_id, tenant_id)",
      "on pact_publication (pact_version_id, consumer_id, provider_id)",
      "on pact_publication (provider_id, consumer_id)",
    ]) {
      expect(ddl).toContain(index);
    }
  });
});
