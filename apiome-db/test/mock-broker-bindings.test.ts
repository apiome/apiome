/**
 * Structural assertions over the mock broker bindings migration (#5735, XPC-2.1).
 *
 * V372 adds `apiome.mock_broker_bindings` — where a version's hosted mock publishes AsyncAPI events
 * (a tenant's own Kafka cluster), with the SASL credential to present sealed as ciphertext.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's
 * acceptance criteria turn into schema rules:
 *
 *   1. **The credential is ciphertext, and only ciphertext.** `credential_ciphertext BYTEA` plus the
 *      `key_version` that sealed it; no column a plaintext username, password or digest could be
 *      written to.
 *   2. **A credential exists exactly when a SASL mechanism does** (one CHECK keeps the three
 *      columns together).
 *   3. **The address is a bounded `host:port` list**, never a URL.
 *   4. **One binding per version and protocol**, cascading from the version and the tenant.
 *
 * There is deliberately **no new RBAC resource**: the API reuses `versions`.
 *
 * These must stay in lock-step with apiome-rest's `app.mock_broker_bindings` contract and its
 * `tests/test_mock_broker_bindings_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V372__mock_broker_bindings_xpc_2_1.sql";
const TABLE = "mock_broker_bindings";

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

/** The body of the `CREATE TABLE` statement, lower-cased and without comments. */
function tableBody(): string {
  const start = ddl.indexOf(`create table if not exists ${TABLE} (`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf("\n);", start));
}

describe("mock broker bindings migration", () => {
  it("is present in scripts/ and ordered after the XPC-1.2 contract protocol migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V371__contract_protocol_xpc_1_2.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toContain(`create table if not exists ${TABLE} (`);
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — the credential is ciphertext, and only ciphertext", () => {
    it("stores it as BYTEA with the key version that sealed it", () => {
      expect(lower).toContain("credential_ciphertext bytea,");
      expect(lower).toContain("key_version integer");
      expect(lower).toContain("check (key_version >= 1)");
    });

    it("opens no column a plaintext credential or a digest of one could be written to", () => {
      const body = tableBody();
      for (const column of ["password", "username", "secret", "plaintext", "fingerprint", "token"]) {
        expect(body).not.toContain(column);
      }
    });
  });

  describe("rule 2 — a credential exists exactly when a SASL mechanism does", () => {
    it("limits the mechanisms to the three that take a username and password", () => {
      expect(sql).toContain("CHECK (sasl_mechanism IN ('PLAIN', 'SCRAM-SHA-256', 'SCRAM-SHA-512'))");
    });

    it("keeps mechanism, ciphertext and key version together", () => {
      expect(sql).toContain(
        "(sasl_mechanism IS NULL AND credential_ciphertext IS NULL AND key_version IS NULL)",
      );
      expect(sql).toMatch(
        /sasl_mechanism IS NOT NULL\s+AND credential_ciphertext IS NOT NULL\s+AND key_version IS NOT NULL/,
      );
    });
  });

  describe("rule 3 — the address is a bounded host:port list", () => {
    it("bounds the list and checks the shape of every entry", () => {
      expect(lower).toContain("bootstrap text[] not null");
      expect(lower).toContain("check (cardinality(bootstrap) between 1 and 16)");
      expect(lower).toContain("array_to_string(bootstrap, ',')");
    });

    it("carries the TLS flags with safe defaults", () => {
      expect(lower).toContain("tls_enabled boolean not null default false");
      expect(lower).toContain("tls_verify boolean not null default true");
    });
  });

  describe("rule 4 — one binding per version and protocol", () => {
    it("reserves mqtt and amqp beside kafka", () => {
      expect(sql).toContain("CHECK (protocol IN ('kafka', 'mqtt', 'amqp'))");
    });

    it("is unique on (version_id, protocol)", () => {
      expect(lower).toContain(`create unique index if not exists idx_${TABLE}_version_protocol`);
      expect(lower).toContain(`on ${TABLE} (version_id, protocol)`);
    });

    it("cascades from the version and the tenant", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(lower).toContain("version_id uuid not null references versions(id) on delete cascade");
    });

    it("tracks rotation in place", () => {
      expect(lower).toContain("rotated_at timestamptz");
      expect(lower).toContain("rotated_by uuid references users(id) on delete set null");
    });
  });

  describe("no new RBAC resource", () => {
    it("leaves seed_builtin_roles and the permission tables alone", () => {
      expect(ddl).not.toContain("seed_builtin_roles");
      expect(ddl).not.toContain("role_permissions");
    });
  });
});
