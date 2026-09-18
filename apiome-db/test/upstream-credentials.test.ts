/**
 * Structural assertions over the upstream auth vault migration (#4534, AGX-2.2).
 *
 * V268 adds `apiome.upstream_credentials` — the sealed credential a managed MCP toolset presents
 * to a tenant's real API, so an agent never holds it — and `apiome.upstream_credential_uses`, the
 * metadata-only record of each use.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's
 * acceptance criteria turn into schema rules rather than habits:
 *
 *   1. **The secret is ciphertext, and only ciphertext.** `encrypted_secret BYTEA` plus the
 *      `key_version` that sealed it; there is no column a plaintext secret, or a digest of one,
 *      could be written to.
 *   2. **Bound to a toolset and a server URL.** https-only, no userinfo / query / fragment, one
 *      credential per (tenant, toolset, server URL). `toolset_id` has no FK yet: `agent_toolsets`
 *      is AGX-1.2 (#4530), which adds it.
 *   3. **Only the placement is in the clear.** `kind` in OpenAPI's vocabulary; `in` / `name` exist
 *      exactly for `apiKey`, and the name keeps to the RFC 9110 token grammar.
 *   4. **Rotation happens in place** — `rotated_at` / `rotated_by` on the same row.
 *   5. **Use is audited as metadata only.** The ledger is write-once (V128 guard), has no secret
 *      or request column, outlives its credential (no FK on `credential_id`), and is bounded by a
 *      purge function.
 *
 * There is deliberately **no new RBAC resource**: the API reuses `api_keys`.
 *
 * These must stay in lock-step with apiome-rest's `app.upstream_credentials` /
 * `app.upstream_credential_binding` contracts and their
 * `tests/test_upstream_credentials_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V268__upstream_credentials_agx_2_2.sql";
const CREDENTIALS = "upstream_credentials";
const USES = "upstream_credential_uses";

let sql = "";
let lower = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — for negative checks. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?;/g, "")
    .toLowerCase();
});

/** The body of one `CREATE TABLE` statement, lower-cased and without comments. */
function tableBody(table: string): string {
  const start = ddl.indexOf(`create table if not exists ${table} (`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf("\n);", start));
}

describe("upstream credentials migration", () => {
  it("is present in scripts/ and ordered after the check-suite migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V267__api_check_suite_gnc_3_1.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(new RegExp(`create table if not exists ${CREDENTIALS} \\(`));
    expect(lower).toMatch(new RegExp(`create table if not exists ${USES} \\(`));
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — the secret is ciphertext, and only ciphertext", () => {
    it("stores it as BYTEA with the key version that sealed it", () => {
      expect(lower).toContain("encrypted_secret bytea not null");
      expect(lower).toContain("key_version integer not null");
      expect(lower).toContain("check (key_version >= 1)");
    });

    it("opens no column a plaintext secret or a digest of one could be written to", () => {
      const body = tableBody(CREDENTIALS);
      for (const column of [
        "secret text",
        "secret varchar",
        "token text",
        "password",
        "username",
        "plaintext",
        "fingerprint",
        "metadata",
      ]) {
        expect(body).not.toContain(column);
      }
    });
  });

  describe("rule 2 — bound to a toolset and a server URL", () => {
    it("requires an https URL with no userinfo, query or fragment", () => {
      expect(sql).toContain(
        "CHECK (server_url ~ '^https://[^/?#@[:space:]]+(/[^?#[:space:]]*)?$')",
      );
      expect(lower).toContain("check (char_length(server_url) <= 2048)");
    });

    it("keeps one credential per tenant, toolset and server", () => {
      expect(lower).toContain(`create unique index if not exists idx_${CREDENTIALS}_binding`);
      expect(lower).toContain(`on ${CREDENTIALS} (tenant_id, toolset_id, server_url)`);
    });

    it("cascades from the tenant, and has no toolset FK until AGX-1.2", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(ddl).toContain("toolset_id uuid not null,");
      expect(ddl).not.toContain("references agent_toolsets");
    });
  });

  describe("rule 3 — only the placement is in the clear", () => {
    it("constrains the kind to OpenAPI's three", () => {
      expect(sql).toContain("CHECK (kind IN ('apiKey', 'bearer', 'basic'))");
    });

    it("gives in/name to apiKey only, with a token-grammar name", () => {
      expect(sql).toContain("AND api_key_in IN ('header', 'query')");
      expect(sql).toContain("AND api_key_name ~ '^[!#$%&''*+.^_`|~0-9A-Za-z-]+$'");
      expect(sql).toContain(
        "OR (kind <> 'apiKey' AND api_key_in IS NULL AND api_key_name IS NULL)",
      );
    });
  });

  describe("rule 4 — rotation happens in place", () => {
    it("tracks when and by whom on the same row", () => {
      expect(lower).toContain("rotated_at timestamptz");
      expect(lower).toContain("rotated_by uuid references users(id) on delete set null");
    });
  });

  describe("rule 5 — use is audited as metadata only", () => {
    it("records which credential, which toolset, when and the outcome", () => {
      const body = tableBody(USES);
      expect(body).toContain("credential_id uuid not null,");
      expect(body).toContain("toolset_id uuid not null,");
      expect(body).toContain("used_at timestamptz not null default current_timestamp");
      expect(body).toContain("check (outcome in ('injected', 'unavailable'))");
    });

    it("holds no secret and no request data", () => {
      const body = tableBody(USES);
      for (const column of ["encrypted", "secret", "url", "header", "body", "detail"]) {
        expect(body).not.toContain(column);
      }
    });

    it("outlives the credential (no FK on credential_id)", () => {
      expect(tableBody(USES)).not.toMatch(/credential_id uuid not null references/);
    });

    it("is write-once, via the shared V128 guard", () => {
      expect(lower).toContain(`before update on ${USES}`);
      expect(lower).toContain("execute function mcp_forbid_row_mutation()");
      expect(lower).not.toContain("create or replace function mcp_forbid_row_mutation");
    });

    it("is indexed for last-used lookups and bounded by a purge", () => {
      expect(lower).toContain(`on ${USES} (credential_id, used_at desc)`);
      expect(lower).toContain(`on ${USES} (tenant_id, used_at desc)`);
      expect(lower).toContain(
        "create or replace function purge_upstream_credential_uses(p_retention_days integer default 90)",
      );
    });
  });

  describe("no new RBAC resource", () => {
    it("leaves seed_builtin_roles and the permission tables alone", () => {
      expect(ddl).not.toContain("seed_builtin_roles");
      expect(ddl).not.toContain("role_permissions");
    });
  });
});
