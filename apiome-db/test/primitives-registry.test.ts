/**
 * Structural assertions over the primitives-registry migration (#3446 reversal + #3447 redesign).
 *
 * The type registry is the existing `apiome.primitives` table, extended in place — there is no
 * separate database and no `otr` schema. These tests verify the DDL contract of the
 * consolidation migration without a live database (the package's test suite is DB-free).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V111__consolidate_the_type_registry_into_objec.sql";

let sql = "";

beforeAll(async () => {
  sql = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("primitives registry consolidation migration", () => {
  it("is present in scripts/", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
  });

  it("drops the obsolete separate-registry otr schema", () => {
    expect(sql).toMatch(/drop schema if exists otr cascade/);
  });

  it("extends apiome.primitives (not a new table or schema)", () => {
    expect(sql).toMatch(/alter table\s+primitives\s+add column/);
    expect(sql).not.toMatch(/create table\s+type_namespace/);
    expect(sql).not.toMatch(/create table\s+type_definition/);
    expect(sql).not.toMatch(/create schema/);
  });

  it("adds the registry columns to primitives", () => {
    for (const col of ["namespace", "base_uri", "schema_id", "draft", "source", "refs"]) {
      expect(sql).toContain(`add column if not exists ${col}`);
    }
  });

  it("stores $ref edges as jsonb and source as a constrained value", () => {
    expect(sql).toMatch(/refs\s+jsonb\s+not null/);
    expect(sql).toMatch(/check\s*\(source in \('human', 'imported'\)\)/);
  });

  it("indexes the new registry columns", () => {
    for (const idx of [
      "idx_primitives_namespace",
      "idx_primitives_schema_id",
      "idx_primitives_source",
      "idx_primitives_refs",
    ]) {
      expect(sql).toContain(idx);
    }
  });

  it("never reaches for a separate registry database", () => {
    const noComments = sql.replace(/--[^\n]*/g, "");
    expect(noComments).not.toContain("apiome-types-db");
    expect(noComments).not.toMatch(/create database/);
  });
});
