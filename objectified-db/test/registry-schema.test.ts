/**
 * Structural assertions over the type-registry core schema migration (#3447, 1.2).
 *
 * The objectified-db test suite runs without a live database, so these tests verify
 * the DDL contract of the registry-scripts/ migrations directly: the three core
 * entity tables, their key constraints, and indices land in the `otr` schema of the
 * separate registry database. A live round-trip is exercised by the registry migrate
 * tooling against objectified-types-db in deployment.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const REGISTRY_SCRIPTS_DIR = new URL("../registry-scripts", import.meta.url).pathname;

/** Concatenated SQL of every registry migration, lower-cased for case-insensitive matching. */
let allSql = "";

beforeAll(async () => {
  const files = await listMigrationFiles(REGISTRY_SCRIPTS_DIR);
  const contents = await Promise.all(
    files.map((f) => fs.readFile(path.join(REGISTRY_SCRIPTS_DIR, f), "utf8")),
  );
  allSql = contents.join("\n").toLowerCase();
});

describe("registry baseline", () => {
  it("provisions the otr schema", () => {
    expect(allSql).toContain("create schema if not exists otr");
  });
});

describe("type_namespace table", () => {
  it("is created", () => {
    expect(allSql).toMatch(/create table\s+type_namespace/);
  });

  it("constrains scope to system|tenant", () => {
    expect(allSql).toMatch(/scope[^,]*check\s*\(scope in \('system', 'tenant'\)\)/);
  });

  it("ties tenant_id to scope (system => null, tenant => set)", () => {
    expect(allSql).toContain("type_namespace_scope_tenant_ck");
  });

  it("uniquely indexes namespace path per scope", () => {
    expect(allSql).toContain("uq_type_namespace_system_path");
    expect(allSql).toContain("uq_type_namespace_tenant_path");
  });

  it("declares base_uri, version_root, visibility, and is_default", () => {
    for (const col of ["base_uri", "version_root", "visibility", "is_default"]) {
      expect(allSql).toContain(col);
    }
  });
});

describe("type_definition table", () => {
  it("is created", () => {
    expect(allSql).toMatch(/create table\s+type_definition/);
  });

  it("references its namespace with cascade delete", () => {
    expect(allSql).toMatch(
      /namespace_id\s+uuid\s+not null\s+references\s+type_namespace\s*\(id\)\s+on delete cascade/,
    );
  });

  it("stores json_schema as not-null jsonb", () => {
    expect(allSql).toMatch(/json_schema\s+jsonb\s+not null/);
  });

  it("enforces unique (namespace_id, name)", () => {
    expect(allSql).toMatch(
      /create unique index\s+uq_type_definition_namespace_name\s+on type_definition \(namespace_id, name\)/,
    );
  });

  it("constrains source and mutability", () => {
    expect(allSql).toMatch(/source[^,]*check\s*\(source in \('human', 'imported'\)\)/);
    expect(allSql).toMatch(/mutability[^,]*check\s*\(mutability in \('mutable', 'immutable'\)\)/);
  });
});

describe("type_ref table", () => {
  it("is created", () => {
    expect(allSql).toMatch(/create table\s+type_ref/);
  });

  it("references the source type definition with cascade delete", () => {
    expect(allSql).toMatch(
      /source_type_id\s+uuid\s+not null\s+references\s+type_definition\s*\(id\)\s+on delete cascade/,
    );
  });

  it("constrains status to resolved|unresolved|circular", () => {
    expect(allSql).toMatch(
      /status[^,]*check\s*\(status in \('resolved', 'unresolved', 'circular'\)\)/,
    );
  });

  it("records relative_ref and resolved_target", () => {
    expect(allSql).toContain("relative_ref");
    expect(allSql).toContain("resolved_target");
  });

  it("uniquely indexes (source_type_id, relative_ref)", () => {
    expect(allSql).toContain("uq_type_ref_source_relative");
  });
});

describe("cross-database isolation", () => {
  it("declares no foreign key or query against the core odb schema", () => {
    // Comments may mention odb for context; DDL/DML must never reach across databases.
    const sqlNoComments = allSql.replace(/--[^\n]*/g, "");
    expect(sqlNoComments).not.toMatch(/references\s+odb\b/);
    expect(sqlNoComments).not.toMatch(/\b(from|join|into|update)\s+odb\./);
  });
});
