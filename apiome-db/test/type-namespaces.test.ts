/**
 * Structural assertions over the type-registry namespace migration (#3451).
 *
 * The namespace registry adds a small `apiome.type_namespaces` table in the existing `apiome` schema
 * (same database — no separate registry DB), because the Namespace CRUD API must create a
 * namespace before it has any types and persist its default/visibility flags, neither of which
 * fits on the per-type `apiome.primitives` rows. The table's `namespace`/`base_uri` columns mirror
 * those on `apiome.primitives`, the type-count join key. These tests verify the DDL contract without
 * a live database (the package's test suite is DB-free).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V114__namespace_registry_for_the_type_registry.sql";

let sql = "";

beforeAll(async () => {
  sql = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("type-registry namespace migration", () => {
  it("is present in scripts/", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
  });

  it("creates apiome.type_namespaces in the existing apiome schema (no new schema/database)", () => {
    expect(sql).toMatch(/create table if not exists apiome\.type_namespaces/);
    expect(sql).not.toMatch(/create schema/);
    expect(sql).not.toMatch(/create database/);
    expect(sql).not.toContain("apiome-types-db");
  });

  it("carries scope, base-uri, version-root, visibility, and default columns", () => {
    for (const col of [
      "tenant_id",
      "namespace",
      "base_uri",
      "version_root",
      "is_system",
      "is_public",
      "is_default",
    ]) {
      expect(sql).toContain(col);
    }
  });

  it("scopes ownership with a tenant FK that is nullable for system-core namespaces", () => {
    expect(sql).toMatch(/tenant_id\s+uuid\s+references\s+apiome\.tenants\(id\)\s+on delete cascade/);
  });

  it("enforces per-scope path uniqueness with partial unique indexes", () => {
    expect(sql).toMatch(/unique index[^;]*type_namespaces[^;]*\(namespace\)\s+where is_system/);
    expect(sql).toMatch(
      /unique index[^;]*type_namespaces[^;]*\(tenant_id, namespace\)\s+where not is_system/,
    );
  });

  it("seeds the std/v0 system-core namespaces idempotently", () => {
    expect(sql).toContain("std/v0/primitives");
    expect(sql).toContain("std/v0/types");
    expect(sql).toMatch(/on conflict do nothing/);
  });
});
