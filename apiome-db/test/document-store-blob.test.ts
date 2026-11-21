/**
 * Structural assertions over the document store blob migration (#7077, COA-5.1).
 *
 * V402 is the `db` backend of apiome-rest's document store. DB-free contract tests pin its rules:
 *
 *   1. **One row per tenant and SHA-256** — a second write of the same bytes is a no-op.
 *   2. **Tenant isolation** — the tenant is part of the key, with a safe-segment check.
 *   3. **The digest is lower-case hex** and the recorded size matches the bytes.
 *
 * These must stay in lock-step with apiome-rest's `app.document_store.DbDocumentStore`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V402__document_store_blob_7077.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

describe("document store blob migration (COA-5.1)", () => {
  it("is present in scripts/ and ordered after the Arazzo fix rules reseed", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V401__style_guide_builtin_reseed_arazzo_fix_rules_5880.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("keeps one row per tenant and digest", () => {
    expect(ddl).toContain("primary key (tenant_id, sha256)");
  });

  it("accepts only a safe tenant key segment", () => {
    expect(ddl).toContain("check (tenant_id ~ '^[a-za-z0-9][a-za-z0-9._-]{0,127}$')");
  });

  it("accepts only a lower-case hex SHA-256", () => {
    expect(ddl).toContain("check (sha256 ~ '^[0-9a-f]{64}$')");
  });

  it("records a size that matches the bytes", () => {
    expect(ddl).toContain("check (octet_length(content) = size_bytes)");
  });

  it("documents its rollback", () => {
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.document_store_blob;");
  });
});
