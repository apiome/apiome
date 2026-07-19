/**
 * Structural assertions over the operational component library migration
 * (DCW-3.1, private-suite#2353).
 *
 * The library is modeled separately from project versions: stable component
 * identity, immutable published semver revisions, project pins that use
 * exactly the revision they pinned, and an append-only audit ledger. These
 * tests verify the DDL contract without a live database (the package's test
 * suite is DB-free): tenant scoping, the kind vocabulary, the draft/published
 * lifecycle columns, the ON DELETE RESTRICT backstops for in-use revisions
 * and pinned Type Registry entries, and collision-safe naming constraints.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V186__operational_components_2353.sql";

let sql = "";

beforeAll(async () => {
  sql = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("operational component library migration", () => {
  it("is present in scripts/", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
  });

  it("creates the four library tables in the existing apiome schema (no new schema/database)", () => {
    for (const table of [
      "operational_components",
      "operational_component_revisions",
      "version_component_pins",
      "component_library_audit",
    ]) {
      expect(sql).toMatch(new RegExp(`create table if not exists apiome\\.${table}`));
    }
    expect(sql).not.toMatch(/create schema/);
    expect(sql).not.toMatch(/create database/);
  });

  it("scopes every table to a tenant with a cascading FK", () => {
    const matches = sql.match(
      /tenant_id uuid not null references apiome\.tenants\(id\) on delete cascade/g,
    );
    expect(matches?.length).toBe(4);
  });

  it("constrains the component kind to the DCW-3.1 vocabulary", () => {
    expect(sql).toContain("'parameter'");
    expect(sql).toContain("'header'");
    expect(sql).toContain("'requestbody'");
    expect(sql).toContain("'response'");
    expect(sql).toContain("'securitybundle'");
    expect(sql).toContain("'schema'");
  });

  it("keeps live component names unique per tenant and kind (soft-delete aware)", () => {
    expect(sql).toMatch(
      /unique index[^;]*operational_components[^;]*\(tenant_id, kind, name\)\s+where deleted_at is null/,
    );
  });

  it("models the minimal MVP lifecycle: semver revisions with draft/published state", () => {
    expect(sql).toMatch(/revision ~ '\^\[0-9\]\+\\\.\[0-9\]\+\\\.\[0-9\]\+\$'/);
    expect(sql).toMatch(/state in \('draft', 'published'\)/);
    for (const col of ["canonical_payload jsonb not null", "payload_digest", "published_at", "published_by"]) {
      expect(sql).toContain(col);
    }
    expect(sql).toMatch(/unique \(component_id, revision\)/);
  });

  it("pins schema-kind revisions to Type Registry entries with a RESTRICT backstop", () => {
    expect(sql).toMatch(
      /schema_primitive_id uuid references apiome\.primitives\(id\) on delete restrict/,
    );
  });

  it("backstops in-use revisions at the database: pins RESTRICT their revision", () => {
    expect(sql).toMatch(
      /component_revision_id uuid not null\s+references apiome\.operational_component_revisions\(id\) on delete restrict/,
    );
  });

  it("keeps one live pin per (version, revision) and indexes live pins by version", () => {
    expect(sql).toMatch(
      /unique index[^;]*version_component_pins[^;]*\(version_id, component_revision_id\)\s+where deleted_at is null/,
    );
    expect(sql).toMatch(/index[^;]*version_component_pins[^;]*\(version_id\)\s+where deleted_at is null/);
  });

  it("enforces OpenAPI-component-key-safe names for components and pin overrides", () => {
    const shapeMatches = sql.match(/\^\[a-za-z\]\[a-za-z0-9_.-\]\{0,127\}\$/g);
    expect(shapeMatches?.length).toBe(2);
  });

  it("records an append-only audit ledger without FKs to the mutated subjects", () => {
    const auditDdl = sql.slice(sql.indexOf("apiome.component_library_audit ("));
    const auditTable = auditDdl.slice(0, auditDdl.indexOf(");"));
    expect(auditTable).toContain("action text not null");
    expect(auditTable).toContain("outcome text not null default 'success'");
    // Subject ids stay plain UUIDs so history survives component/revision deletes.
    expect(auditTable).not.toMatch(/component_id uuid[^,]*references/);
    expect(auditTable).not.toMatch(/revision_id uuid[^,]*references/);
  });
});
