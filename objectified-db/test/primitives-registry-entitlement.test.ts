/**
 * Structural assertions over the primitives-registry entitlement seed migration (#3478).
 *
 * The migration seeds the `primitives-registry` feature flag (which gates the advanced Type
 * Registry surface in objectified-rest) and bundles it into the Paid and Sponsor license
 * plans — but not Free. These tests verify the seed contract without a live database (the
 * package's test suite is DB-free).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V116__primitives_type_registry_entitlement_fea.sql";

let sql = "";

beforeAll(async () => {
  sql = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("primitives-registry entitlement seed migration", () => {
  it("is present in scripts/", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
  });

  it("seeds the primitives-registry feature flag into odb.feature_flags", () => {
    expect(sql).toMatch(/insert into odb\.feature_flags/);
    expect(sql).toContain("'primitives-registry'");
    // Idempotent re-seed — must not clobber admin edits on re-run.
    expect(sql).toMatch(/on conflict \(name\) do nothing/);
  });

  it("bundles the flag into the Paid and Sponsor plans but not Free", () => {
    expect(sql).toMatch(/insert into odb\.license_feature_flags/);
    expect(sql).toMatch(/l\.name = 'paid'/);
    expect(sql).toMatch(/l\.name = 'sponsor'/);
    // Free is intentionally excluded — no association row references it.
    expect(sql).not.toMatch(/l\.name = 'free'/);
  });

  it("extends existing tables in place — defines no new tables or schema", () => {
    expect(sql).not.toMatch(/create table/);
    expect(sql).not.toMatch(/create schema/);
  });
});
