/**
 * Structural assertions over the schema-registry connector migration (MFI-12.3, #3784).
 *
 * V300 records where a mirrored schema subject came from: `schema_subjects.source_ref` /
 * `source_connector_id`, and the upstream version and schema id of each mirrored version.
 * DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V300__schema_registry_connector_mfi_12_3.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("schema-registry connector migration (MFI-12.3)", () => {
  it("is present in scripts/ and ordered after V299", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V299__catalog_components_cdg_5_5.sql"));
  });

  it("targets the apiome schema and is re-runnable", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).not.toMatch(/add column (?!if not exists)/);
    expect(lower).not.toMatch(/create (unique )?index (?!if not exists)/);
  });

  it("records a registry source ref and the owning connector, kept when the connector is deleted", () => {
    expect(lower).toContain("add column if not exists source_ref text");
    expect(lower).toContain("source_ref like 'registry:%'");
    expect(lower).toMatch(/source_connector_id uuid\s+references apiome\.catalog_connectors\(id\) on delete set null/);
  });

  it("keeps the upstream coordinates of each mirrored version, one local version per upstream version", () => {
    expect(lower).toContain("add column if not exists upstream_version integer");
    expect(lower).toContain("add column if not exists upstream_schema_id integer");
    expect(lower).toMatch(
      /create unique index if not exists uq_schema_subject_versions_upstream\s+on apiome\.schema_subject_versions \(subject_id, upstream_version\)\s+where upstream_version is not null/,
    );
  });

  it("documents its rollback", () => {
    expect(lower).toContain("-- rollback:");
    expect(lower).toContain("drop column if exists source_connector_id");
  });
});
