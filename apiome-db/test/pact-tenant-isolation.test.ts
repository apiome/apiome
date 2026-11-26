/**
 * Structural assertions over the Pact tenant-isolation migration (#6953, PFX-6.1).
 *
 * V447 turns the last three single-column references between tenant-carrying Pact rows into
 * composite (…, tenant_id) references, so the database refuses a row of one tenant that names a row
 * of another. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first.
 *   2. Each superseded single-column key is dropped and its composite replacement added, keeping the
 *      delete behaviour (CASCADE for the delivery and the firing, SET NULL (repository_id) for the
 *      commit status).
 *   3. The referenced tables gain UNIQUE (id, tenant_id), and each new key gets an index led by its
 *      columns (the #7195 coverage gate) before the single-column index it replaces is dropped.
 *   4. It is idempotent: every constraint is added only when it is missing.
 *
 * `apiome-rest/tests/test_pact_tenant_isolation_migration.py` replays every PFX migration and checks
 * that no single-column reference is left; `test_pact_tenant_isolation_db.py` proves the refusals.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V447__pact_tenant_isolation_6953.sql";

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

describe("pact tenant-isolation migration (PFX-6.1)", () => {
  it("is present in scripts/ and ordered after the migrations it tightens", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V436__pact_webhooks_6922.sql"));
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V443__pact_commit_statuses_6941.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it.each([
    [
      "push_webhook_delivery_events_pact_webhook_id_fkey",
      "push_webhook_delivery_events_pact_webhook_fk foreign key (pact_webhook_id, tenant_id) references apiome.pact_webhook (id, tenant_id) on delete cascade",
    ],
    [
      "pact_triggered_webhook_delivery_event_id_fkey",
      "pact_triggered_webhook_delivery_fk foreign key (delivery_event_id, tenant_id) references apiome.push_webhook_delivery_events (id, tenant_id) on delete cascade",
    ],
    [
      "pact_commit_status_repository_id_fkey",
      "pact_commit_status_repository_fk foreign key (repository_id, tenant_id) references apiome.tenant_repositories (id, tenant_id) on delete set null (repository_id)",
    ],
  ])("replaces %s with a composite key", (superseded, composite) => {
    const dropped = ddl.indexOf(`drop constraint if exists ${superseded};`);
    const added = ddl.indexOf(`add constraint ${composite}`);
    expect(dropped).toBeGreaterThan(0);
    expect(added).toBeGreaterThan(dropped);
  });

  it("gives the referenced tables the (id, tenant_id) key the references need", () => {
    expect(ddl).toContain("add constraint push_webhook_delivery_events_id_tenant_key unique (id, tenant_id)");
    expect(ddl).toContain("add constraint tenant_repositories_id_tenant_key unique (id, tenant_id)");
  });

  it("indexes each new key before dropping the single-column index it replaces", () => {
    const indexes = [
      "on push_webhook_delivery_events (pact_webhook_id, tenant_id) where pact_webhook_id is not null",
      "on pact_triggered_webhook (delivery_event_id, tenant_id)",
      "on pact_commit_status (repository_id, tenant_id) where repository_id is not null",
    ];
    for (const index of indexes) expect(ddl).toContain(index);
    const lastCreate = Math.max(...indexes.map((index) => ddl.indexOf(index)));
    expect(ddl.indexOf("drop index if exists idx_push_webhook_delivery_events_pact_webhook;")).toBeGreaterThan(lastCreate);
    expect(ddl.indexOf("drop index if exists idx_pact_commit_status_repository;")).toBeGreaterThan(lastCreate);
  });

  it("adds every constraint only when it is missing, so a re-run is a no-op", () => {
    const adds = ddl.match(/add constraint (\w+)/g) ?? [];
    expect(adds).toHaveLength(5);
    for (const add of adds) {
      const name = add.replace("add constraint ", "");
      expect(ddl).toContain(`where conname = '${name}'`);
    }
  });
});
