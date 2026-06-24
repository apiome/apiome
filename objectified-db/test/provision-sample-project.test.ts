/**
 * Structural assertions over the sample-project provisioning migration (#3614).
 *
 * V122 adds the shared `odb.provision_sample_project()` routine that seeds a curated, published,
 * public "Pet Store" sample so a fresh tenant is never empty. These tests verify the migration's
 * contract — the function exists, populates the full project graph, marks the version published +
 * public, is idempotent, and every embedded JSON literal is valid — without a live database (this
 * package's suite is DB-free, so PL/pgSQL is not executed here; the end-to-end render is proven by
 * the objectified-rest pytest).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V122__provision_sample_project_petstore.sql";

let sql = "";
let lower = "";

/** Every `'{...}'::jsonb` literal in the migration (one per line), JSON-parsed. */
function jsonbLiterals(): unknown[] {
  return sql
    .split("\n")
    .map((line) => line.match(/'(\{.*\})'::jsonb/)) // greedy within a single line
    .filter((m): m is RegExpMatchArray => m !== null)
    .map((m) => JSON.parse(m[1] as string));
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("sample-project provisioning migration", () => {
  it("is present in scripts/ and ordered after V121", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V121__rbac_member_status_and_platform_admins.sql"),
    );
  });

  it("defines the shared provisioning function (rerun-safe)", () => {
    expect(lower).toMatch(/create or replace function odb\.provision_sample_project\(/);
    expect(lower).toContain("returns uuid");
    expect(lower).toContain("language plpgsql");
  });

  it("is idempotent: skips when the sample already exists for the tenant", () => {
    expect(lower).toMatch(/if exists \(\s*select 1 from odb\.projects/);
    expect(sql).toContain("slug = 'petstore-sample'");
    expect(lower).toContain("return null");
  });

  it("populates the full project graph", () => {
    for (const table of [
      "odb.projects",
      "odb.versions",
      "odb.classes",
      "odb.properties",
      "odb.class_properties",
      "odb.class_schema",
    ]) {
      expect(lower).toContain(`insert into ${table}`);
    }
  });

  it("creates a PUBLISHED, PUBLIC version (required for Browse)", () => {
    expect(lower).toContain("published");
    expect(sql).toContain("'public'");
    // published flag + visibility appear in the versions insert.
    expect(sql).toMatch(/published_at/);
  });

  it("creates the three sample classes", () => {
    for (const name of ["'Category'", "'Tag'", "'Pet'"]) {
      expect(sql).toContain(name);
    }
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    // Base tables default to uuid_generate_v4(); the function relies on those defaults and must not
    // introduce gen_random_uuid (kept consistent with the rest of the schema).
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("every embedded JSON literal is valid JSON", () => {
    expect(() => jsonbLiterals()).not.toThrow();
    // 3 property defs + 7 class_property fields + 3 frozen class schemas + 3 class base schemas = 16.
    expect(jsonbLiterals().length).toBeGreaterThanOrEqual(16);
  });

  it("marks required fields and enumerates pet status", () => {
    const docs = jsonbLiterals() as Record<string, unknown>[];
    const withRequired = docs.filter((d) => d.required === true);
    expect(withRequired.length).toBeGreaterThan(0);
    const statusDoc = docs.find((d) => Array.isArray(d.enum));
    expect(statusDoc?.enum).toEqual(["available", "pending", "sold"]);
  });
});
