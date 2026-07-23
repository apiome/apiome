/**
 * Structural assertions over the auth_provider_config migration (#4968, OLO-8.2).
 *
 * V196 creates `apiome.auth_provider_config` — the server-GLOBAL OAuth provider config
 * store (one row per provider), distinct from the per-tenant `*_settings` pattern. It
 * overlays env config field-by-field: an absent row, or a null field, falls back to env
 * (OLO-8.5). The client secret is ciphertext-only (BYTEA) with an enc_key_id for rotation
 * (OLO-8.3), and the two travel together.
 *
 * These are DB-free contract tests pinning the migration's shape — the columns, the
 * provider-id enum guard, the secret/key consistency constraint, the touch trigger, and
 * the env-fallback documentation the apiome-ui/apiome-rest config layers depend on.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V196__auth_provider_config_4968.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("auth_provider_config migration (OLO-8.2)", () => {
  it("is present in scripts/ and ordered after V195", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V195__license_quota_limits_64.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the global auth_provider_config table (not a per-tenant *_settings table)", () => {
    expect(lower).toMatch(
      /create table if not exists apiome\.auth_provider_config/,
    );
    // Global config — keyed by provider, never by tenant. (The header comment may mention
    // tenant_id when contrasting with the per-tenant *_settings pattern; guard the column
    // definition, not the prose.)
    expect(lower).not.toMatch(/tenant_id\s+uuid/);
    expect(lower).not.toMatch(/references\s+apiome\.tenants/);
  });

  it("documents the rollback drop", () => {
    expect(lower).toContain(
      "drop table if exists apiome.auth_provider_config cascade",
    );
    expect(lower).toContain(
      "drop function if exists apiome.update_auth_provider_config_updated_at()",
    );
  });

  describe("columns", () => {
    it("keys on provider_id as a text primary key", () => {
      expect(lower).toMatch(/provider_id text primary key/);
    });

    it("carries the enabled toggle, client_id, config, and audit columns", () => {
      expect(lower).toMatch(/enabled boolean/);
      expect(lower).toMatch(/client_id text/);
      expect(lower).toMatch(/config jsonb not null default '\{\}'::jsonb/);
      expect(lower).toMatch(/updated_at timestamptz not null default current_timestamp/);
      expect(lower).toMatch(/updated_by text/);
    });

    it("stores the client secret as ciphertext-only BYTEA with a rotation key id", () => {
      expect(lower).toMatch(/client_secret_encrypted bytea/);
      expect(lower).toMatch(/enc_key_id text/);
    });

    it("leaves every configurable field nullable (only provider_id/config/updated_at are NOT NULL)", () => {
      // The secret must be nullable so a provider can be enable-toggled or partially configured.
      expect(lower).not.toMatch(/client_secret_encrypted bytea not null/);
      expect(lower).not.toMatch(/enabled boolean not null/);
      expect(lower).not.toMatch(/client_id text not null/);
      expect(lower).not.toMatch(/enc_key_id text not null/);
    });
  });

  describe("constraints", () => {
    it("guards provider_id against unknown providers (PROVIDER_REGISTRY vocabulary)", () => {
      expect(lower).toMatch(/auth_provider_config_provider_id_check/);
      for (const id of ["github", "gitlab", "azure", "google", "aws"]) {
        expect(lower).toContain(`'${id}'`);
      }
    });

    it("requires ciphertext and its key id to travel together", () => {
      expect(lower).toMatch(/auth_provider_config_secret_key_consistent/);
      expect(lower).toMatch(
        /client_secret_encrypted is null and enc_key_id is null/,
      );
      expect(lower).toMatch(
        /client_secret_encrypted is not null and enc_key_id is not null/,
      );
    });
  });

  describe("updated_at maintenance", () => {
    it("defines the touch trigger function and BEFORE UPDATE trigger", () => {
      expect(lower).toMatch(
        /create or replace function update_auth_provider_config_updated_at\(\)/,
      );
      expect(lower).toMatch(
        /before update on apiome\.auth_provider_config/,
      );
      expect(lower).toMatch(/new\.updated_at = current_timestamp/);
    });
  });

  describe("documentation", () => {
    it("documents the table and key columns", () => {
      expect(lower).toMatch(/comment on table apiome\.auth_provider_config is/);
      expect(lower).toMatch(
        /comment on column apiome\.auth_provider_config\.client_secret_encrypted is/,
      );
      expect(lower).toMatch(
        /comment on column apiome\.auth_provider_config\.enc_key_id is/,
      );
    });

    it("notes the env-fallback semantics (OLO-8.5) and the issue/epic", () => {
      expect(lower).toContain("fall back to env");
      expect(sql).toMatch(/OLO-8\.5/);
      expect(sql).toMatch(/#4968/);
      expect(sql).toMatch(/OLO-8\.2/);
    });
  });
});
