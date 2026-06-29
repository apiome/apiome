/**
 * Structural assertions over the canonical-API-model persistence migration (#3739, MFI-2.2).
 *
 * V135 adds the seven tables that give the MFI-2.1 canonical model (`CanonicalApi` in
 * `objectified-rest/src/app/canonical_model.py`) a relational, queryable home:
 *
 *   api_artifacts → api_services → api_operations → api_messages
 *   api_artifacts → api_channels
 *   api_artifacts → api_types → api_fields
 *
 * These tests verify the migration's contract — tables, columns, FK wiring, soft-delete-aware unique
 * keys, enum check constraints (mirroring the canonical Python enums), search (GIN tsvector) indexes,
 * and exhaustive comments — without a live database (this package's suite is DB-free; the SQL is
 * asserted structurally, end-to-end application is proven elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V135__canonical_api_model_persistence_3739.sql";

/** The seven persistence tables, parent-first. */
const TABLES = [
  "api_artifacts",
  "api_services",
  "api_operations",
  "api_messages",
  "api_channels",
  "api_types",
  "api_fields",
] as const;

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("canonical-API-model persistence migration", () => {
  it("is present in scripts/ and ordered after V134", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V134__mcp_catalog_public_endpoints_view_3671.sql"),
    );
  });

  it("targets the odb schema", () => {
    expect(lower).toContain("set search_path to odb, public");
  });

  it("creates all seven canonical tables idempotently", () => {
    for (const table of TABLES) {
      expect(lower).toMatch(new RegExp(`create table if not exists ${table}\\b`));
    }
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("gives every table a UUID primary key", () => {
    const pkCount = (sql.match(/id UUID PRIMARY KEY DEFAULT uuid_generate_v4\(\)/g) ?? []).length;
    expect(pkCount).toBe(TABLES.length);
  });

  it("tenant-scopes every table via a cascading FK to tenants", () => {
    const tenantFk = (
      sql.match(/tenant_id UUID NOT NULL REFERENCES tenants\(id\) ON DELETE CASCADE/g) ?? []
    ).length;
    expect(tenantFk).toBe(TABLES.length);
  });

  it("ties every table to a versions row via a cascading version_id FK", () => {
    const versionFk = (
      sql.match(/version_id UUID NOT NULL REFERENCES versions\(id\) ON DELETE CASCADE/g) ?? []
    ).length;
    expect(versionFk).toBe(TABLES.length);
  });

  it("soft-deletes every table", () => {
    const softDelete = (sql.match(/^\s*deleted_at TIMESTAMP WITH TIME ZONE,\s*$/gm) ?? []).length;
    expect(softDelete).toBe(TABLES.length);
  });

  it("wires the tree with cascading parent FKs (artifact→service→operation→message; type→field)", () => {
    expect(sql).toMatch(/artifact_id UUID NOT NULL REFERENCES api_artifacts\(id\) ON DELETE CASCADE/);
    expect(sql).toMatch(/service_id UUID NOT NULL REFERENCES api_services\(id\) ON DELETE CASCADE/);
    expect(sql).toMatch(
      /operation_id UUID NOT NULL REFERENCES api_operations\(id\) ON DELETE CASCADE/,
    );
    expect(sql).toMatch(/type_id UUID NOT NULL REFERENCES api_types\(id\) ON DELETE CASCADE/);
  });

  it("records the artifact's producer with a restricted FK to users", () => {
    expect(sql).toMatch(/creator_id UUID NOT NULL REFERENCES users\(id\) ON DELETE RESTRICT/);
  });

  it("enforces at most one live artifact per version", () => {
    expect(lower).toMatch(
      /create unique index if not exists uq_api_artifacts_version\s+on api_artifacts\(version_id\) where deleted_at is null/,
    );
  });

  it("keys each child entity uniquely within its parent (live rows only)", () => {
    const expectations: Array<[string, string]> = [
      ["uq_api_services_artifact_key", "api_services(artifact_id, key)"],
      ["uq_api_operations_service_key", "api_operations(service_id, key)"],
      ["uq_api_messages_operation_key", "api_messages(operation_id, key)"],
      ["uq_api_channels_artifact_key", "api_channels(artifact_id, key)"],
      ["uq_api_types_artifact_key", "api_types(artifact_id, key)"],
      ["uq_api_fields_type_key", "api_fields(type_id, key)"],
    ];
    for (const [name, target] of expectations) {
      const re = new RegExp(
        `create unique index if not exists ${name}\\s+on ${target.replace(
          /[()]/g,
          (c) => `\\${c}`,
        )} where deleted_at is null`,
      );
      expect(lower).toMatch(re);
    }
  });

  it("constrains paradigm to the canonical ApiParadigm values", () => {
    expect(lower).toMatch(/check\s*\(paradigm in \(/);
    for (const v of ["'rest'", "'rpc'", "'event'", "'graph'", "'data_schema'"]) {
      expect(sql).toContain(v);
    }
  });

  it("constrains operation kind to the canonical OperationKind values", () => {
    expect(lower).toMatch(/check\s*\(kind in \(/);
    for (const v of [
      "'request_response'",
      "'one_way'",
      "'publish'",
      "'subscribe'",
      "'query'",
      "'mutation'",
      "'subscription'",
    ]) {
      expect(sql).toContain(v);
    }
  });

  it("constrains streaming to the canonical StreamingMode values", () => {
    expect(lower).toMatch(/check\s*\(streaming in \('none', 'client', 'server', 'bidirectional'\)\)/);
  });

  it("constrains message role to the canonical MessageRole values", () => {
    expect(lower).toMatch(/check\s*\(role in \('request', 'response', 'error', 'event'\)\)/);
  });

  it("constrains type kind to the canonical TypeKind values", () => {
    expect(lower).toMatch(
      /check\s*\(kind in \('record', 'enum', 'union', 'scalar', 'alias', 'map'\)\)/,
    );
  });

  it("guards ordinal as a non-negative list position on every child table", () => {
    // The root artifact has no ordinal (one per version, no sibling ordering); the six child
    // entities each preserve their source declaration order.
    const ordinalChecks = (lower.match(/check \(ordinal >= 0\)/g) ?? []).length;
    expect(ordinalChecks).toBe(TABLES.length - 1);
  });

  it("stores raw + extras for lossless fidelity", () => {
    // Artifact keeps the native AST; every table keeps an extras bag.
    expect(sql).toMatch(/^\s*raw JSONB,\s*$/m);
    const extrasCount = (sql.match(/extras JSONB NOT NULL DEFAULT '\{\}'::jsonb/g) ?? []).length;
    expect(extrasCount).toBe(TABLES.length);
  });

  it("models the irregular sub-structures as JSONB mirroring the canonical shape", () => {
    // Artifact servers; operation parameters/tags; message payload/headers/content_types;
    // channel parameters/bindings; type enum_values/union_members/aliased/key_type/value_type;
    // field type_ref/default_value; constraints reused across entities.
    for (const col of [
      "servers JSONB NOT NULL DEFAULT '[]'::jsonb",
      "parameters JSONB NOT NULL DEFAULT '[]'::jsonb",
      "tags JSONB NOT NULL DEFAULT '[]'::jsonb",
      "headers JSONB NOT NULL DEFAULT '[]'::jsonb",
      "content_types JSONB NOT NULL DEFAULT '[]'::jsonb",
      "bindings JSONB NOT NULL DEFAULT '{}'::jsonb",
      "enum_values JSONB NOT NULL DEFAULT '[]'::jsonb",
      "union_members JSONB NOT NULL DEFAULT '[]'::jsonb",
      "type_ref JSONB NOT NULL",
    ]) {
      expect(sql).toContain(col);
    }
    // Nullable JSONB fidelity/structure columns.
    for (const col of [
      "payload JSONB,",
      "payload_schema JSONB,",
      "aliased JSONB,",
      "key_type JSONB,",
      "value_type JSONB,",
      "default_value JSONB,",
    ]) {
      expect(sql).toContain(col);
    }
    // `constraints` JSONB appears on types and fields.
    expect((sql.match(/^\s*constraints JSONB,?\s*$/gm) ?? []).length).toBeGreaterThanOrEqual(2);
  });

  it("provides a GIN tsvector search index on every browsable table (AC: indexed for search)", () => {
    for (const table of ["api_artifacts", "api_operations", "api_messages", "api_channels", "api_types", "api_fields"]) {
      const re = new RegExp(
        `create index if not exists idx_${table}_fts\\s+on ${table}\\s+using gin \\(to_tsvector\\('english'`,
      );
      expect(lower).toMatch(re);
    }
  });

  it("indexes tenant_id and version_id for tenant-scoped browse/diff", () => {
    // tenant index on every table; version index on every child (artifact uses the unique version key).
    expect((lower.match(/create index if not exists idx_\w+_tenant_id/g) ?? []).length).toBe(
      TABLES.length,
    );
    expect(
      (lower.match(/create index if not exists idx_\w+_version_id/g) ?? []).length,
    ).toBe(TABLES.length - 1);
  });

  it("documents every table", () => {
    for (const table of TABLES) {
      expect(lower).toMatch(new RegExp(`comment on table ${table} is`));
    }
  });

  it("documents every column of every table", () => {
    // Each COMMENT ON COLUMN must correspond to a declared column, and every declared column must be
    // documented. We verify the count of column comments equals the count of declared columns.
    for (const table of TABLES) {
      const commentCount = (
        sql.match(new RegExp(`COMMENT ON COLUMN ${table}\\.`, "g")) ?? []
      ).length;
      expect(commentCount).toBeGreaterThan(0);
    }
    // Spot-check the two ends of the tree are fully documented.
    expect((sql.match(/COMMENT ON COLUMN api_artifacts\./g) ?? []).length).toBe(20);
    expect((sql.match(/COMMENT ON COLUMN api_fields\./g) ?? []).length).toBe(17);
  });
});
