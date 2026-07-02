/**
 * Structural assertions over the MCP credential-vault migration (#3654, V2-MCP-15.4).
 *
 * V129 adds `apiome.mcp_endpoint_credentials`: the encrypted, one-per-endpoint credential store for
 * protected MCP servers. The security contract is that it holds ciphertext only — there is no
 * plaintext secret column — and that it supports all five auth types with exactly one row per
 * endpoint. These tests verify the migration's shape (table + columns + constraints + the
 * updated_at trigger) without a live database (this package's suite is DB-free; the SQL is asserted
 * structurally, end-to-end application is proven elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V129__mcp_catalog_credential_vault_3654.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP credential-vault migration", () => {
  it("is present in scripts/ and ordered after V128", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V128__mcp_catalog_versions_changes_3653.sql"),
    );
  });

  it("creates the table idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_endpoint_credentials/);
  });

  it("defines every column from the ticket's field set", () => {
    for (const col of [
      "id",
      "endpoint_id",
      "auth_type",
      "encrypted_payload",
      "key_version",
      "oauth_metadata",
      "last_refreshed_at",
      "created_at",
      "updated_at",
    ]) {
      // Column declared at the start of a line (after indentation), not merely mentioned in prose.
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
    }
  });

  it("keys credentials to their endpoint and cascades on endpoint delete", () => {
    expect(lower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
  });

  it("enforces one credential row per endpoint via a UNIQUE constraint", () => {
    expect(lower).toMatch(/unique\s*\(endpoint_id\)/);
  });

  it("stores ciphertext only: encrypted_payload is BYTEA and there is no plaintext secret column", () => {
    expect(sql).toMatch(/encrypted_payload BYTEA/);
    // No column that would hold a secret in the clear.
    expect(lower).not.toMatch(/^\s+(secret|token|access_token|refresh_token|plaintext|password)\s/m);
  });

  it("supports all five auth types and constrains auth_type to them", () => {
    expect(lower).toMatch(/check\s*\(auth_type in \(/);
    for (const kind of ["'none'", "'bearer'", "'header'", "'oauth2'", "'env'"]) {
      expect(sql).toContain(kind);
    }
  });

  it("models OAuth2 discovery metadata as cleartext JSONB", () => {
    expect(sql).toMatch(/oauth_metadata JSONB NOT NULL DEFAULT '\{\}'::jsonb/);
  });

  it("tags ciphertext with a key_version for key rotation", () => {
    expect(sql).toMatch(/key_version INTEGER/);
  });

  it("ties ciphertext and key_version together (both present or both absent)", () => {
    expect(lower).toMatch(
      /\(encrypted_payload is null and key_version is null\)\s*or\s*\(encrypted_payload is not null and key_version is not null\)/,
    );
  });

  it("requires ciphertext for every auth type except 'none'", () => {
    expect(lower).toMatch(/auth_type = 'none' and encrypted_payload is null/);
    expect(lower).toMatch(/auth_type <> 'none' and encrypted_payload is not null/);
  });

  it("maintains updated_at with a BEFORE UPDATE trigger (credentials are mutable)", () => {
    expect(lower).toContain(
      "create or replace function update_mcp_endpoint_credentials_updated_at()",
    );
    expect(lower).toMatch(/new\.updated_at = current_timestamp/);
    expect(lower).toMatch(/before update on mcp_endpoint_credentials/);
  });

  it("documents the table and all of its columns", () => {
    expect(lower).toMatch(/comment on table mcp_endpoint_credentials is/);
    const columnComments = (sql.match(/COMMENT ON COLUMN mcp_endpoint_credentials\./g) ?? []).length;
    // 9 columns: id, endpoint_id, auth_type, encrypted_payload, key_version, oauth_metadata,
    // last_refreshed_at, created_at, updated_at — each documented.
    expect(columnComments).toBe(9);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });
});
