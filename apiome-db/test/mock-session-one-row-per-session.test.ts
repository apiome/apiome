/**
 * DBP-1.26 (#7209), migration V430: the mock Postgres session store keeps one row per session
 * (`mock_session`) for expiry and size totals, with resources and id counters as cascading
 * children, and a trigger-kept session count (`mock_session_slots`) for the global cap.
 *
 * Two layers:
 *   1. Structural promises of the migration (order, cascades, indexes, statement-level trigger).
 *   2. Behaviour, on a migrated database: the slot count follows inserts and (multi-row) deletes,
 *      deleting a session cascades, and V430 run over V156's table carries live sessions over and
 *      drops expired rows.
 *
 * Layer 2 needs `APIOME_DB_SCHEMA_TEST_URL` pointing at a database migrated to the current head;
 * without it the block is skipped. Each test runs in a transaction that is rolled back. Locally:
 *
 *     createdb apiome_t && node dist/cli.js migrate --database-url postgresql://localhost/apiome_t
 *     APIOME_DB_SCHEMA_TEST_URL=postgresql://localhost/apiome_t yarn vitest run test/mock-session-one-row-per-session.test.ts
 */

import fs from "node:fs/promises";
import path from "node:path";

import pg from "pg";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V430__mock_session_one_row_per_session_7209.sql";
const PREVIOUS = "V429__mcp_usage_sweep_retention_7206.sql";
const V156 = "V156__mock_session_state_4453.sql";
const SCHEMA_TEST_URL = process.env.APIOME_DB_SCHEMA_TEST_URL?.trim() ?? "";

/** A migration's SQL with `--` comments stripped and whitespace collapsed, lower-cased. */
async function codeOf(file: string): Promise<string> {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

describe("V430: mock session, one row per session", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows V429", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf(PREVIOUS);
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(MIGRATION)).toBe(previous + 1);
  });

  it("keys sessions by namespace and indexes their expiry for the sweep", () => {
    expect(code).toContain(
      "constraint mock_session_namespace_unique unique (tenant_slug, project_slug, version_label, session_token)",
    );
    expect(code).toContain("create index if not exists idx_mock_session_expires on mock_session (expires_at)");
  });

  it("cascades resources and counters with their session, led by session_id", () => {
    for (const table of ["mock_session_resource", "mock_session_counter"]) {
      const start = code.indexOf(`create table if not exists ${table} (`);
      const body = code.slice(start, code.indexOf(");", code.indexOf("primary key", start)) + 2);
      expect(body, table).toContain("session_id bigint not null references mock_session (id) on delete cascade");
      expect(body, table).toMatch(/primary key \(session_id, collection_path/);
    }
  });

  it("keeps the session count with statement-level triggers on insert and delete", () => {
    expect(code).toContain(
      "after insert on mock_session referencing new table as new_sessions for each statement execute function mock_session_slots_count()",
    );
    expect(code).toContain(
      "after delete on mock_session referencing old table as old_sessions for each statement execute function mock_session_slots_count()",
    );
  });

  it("carries live sessions over before dropping the old table", () => {
    const carry = code.indexOf("insert into mock_session_resource");
    const drop = code.indexOf("drop table if exists mock_session_state;");
    expect(carry).toBeGreaterThan(-1);
    expect(drop).toBeGreaterThan(carry);
    expect(code).toContain("where r.expires_at > current_timestamp");
  });
});

describe.skipIf(!SCHEMA_TEST_URL)("V430 on a migrated database", () => {
  let client: pg.Client;

  beforeAll(async () => {
    client = new pg.Client({ connectionString: SCHEMA_TEST_URL });
    await client.connect();
  });

  afterAll(async () => {
    await client?.end();
  });

  beforeEach(async () => {
    await client.query("BEGIN");
  });

  afterEach(async () => {
    await client.query("ROLLBACK");
  });

  async function slotCount(): Promise<number> {
    const { rows } = await client.query("SELECT session_count FROM apiome.mock_session_slots WHERE slot_id = 1");
    return Number(rows[0].session_count);
  }

  async function insertSessions(tokens: string[]): Promise<number[]> {
    const { rows } = await client.query(
      `INSERT INTO apiome.mock_session (tenant_slug, project_slug, version_label, session_token, expires_at, last_activity_at)
       SELECT 't', 'p', '1', token, now() + interval '1 hour', now() FROM unnest($1::text[]) AS token
       RETURNING id`,
      [tokens],
    );
    return rows.map((row) => Number(row.id));
  }

  it("counts inserted and deleted sessions, multi-row statements included", async () => {
    const before = await slotCount();
    const ids = await insertSessions(["a", "b", "c"]);
    expect(await slotCount()).toBe(before + 3);
    await client.query("DELETE FROM apiome.mock_session WHERE id = ANY($1::bigint[])", [ids.slice(0, 2)]);
    expect(await slotCount()).toBe(before + 1);
    // An insert that conflicts inserts nothing and leaves the count alone.
    await client.query(
      `INSERT INTO apiome.mock_session (tenant_slug, project_slug, version_label, session_token, expires_at, last_activity_at)
       VALUES ('t', 'p', '1', 'c', now(), now())
       ON CONFLICT ON CONSTRAINT mock_session_namespace_unique DO NOTHING`,
    );
    expect(await slotCount()).toBe(before + 1);
  });

  it("deletes a session's resources and counters with it", async () => {
    const [id] = await insertSessions(["cascade"]);
    await client.query(
      `INSERT INTO apiome.mock_session_resource (session_id, collection_path, resource_id, resource, byte_size)
       VALUES ($1, '/pets', '1', '{"id": 1}', 8)`,
      [id],
    );
    await client.query(
      "INSERT INTO apiome.mock_session_counter (session_id, collection_path, last_id) VALUES ($1, '/pets', 1)",
      [id],
    );
    await client.query("DELETE FROM apiome.mock_session WHERE id = $1", [id]);
    const { rows } = await client.query(
      `SELECT (SELECT COUNT(*) FROM apiome.mock_session_resource WHERE session_id = $1)::int AS resources,
              (SELECT COUNT(*) FROM apiome.mock_session_counter WHERE session_id = $1)::int AS counters`,
      [id],
    );
    expect(rows[0]).toEqual({ resources: 0, counters: 0 });
  });

  it("carries V156's live sessions over and drops expired rows", async () => {
    // Back to the pre-V430 shape: V156's table with a live two-resource session and an expired one.
    await client.query(
      `DROP TABLE apiome.mock_session_counter, apiome.mock_session_resource, apiome.mock_session_slots, apiome.mock_session`,
    );
    await client.query(await fs.readFile(path.join(SCRIPTS_DIR, V156), "utf8"));
    await client.query(
      `INSERT INTO apiome.mock_session_state (tenant_slug, project_slug, version_label, session_token,
         collection_path, resource_id, resource, byte_size, expires_at, last_activity_at)
       VALUES ('t', 'p', '1', 'live', '/pets', '1', '{"id": 1}', 8, now() + interval '30 minutes', now()),
              ('t', 'p', '1', 'live', '/pets', '2', '{"id": 2}', 8, now() + interval '30 minutes', now()),
              ('t', 'p', '1', 'gone', '/pets', '1', '{"id": 1}', 8, now() - interval '1 minute', now() - interval '1 hour')`,
    );
    await client.query(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));

    const sessions = await client.query(
      "SELECT session_token, resource_count, total_bytes::int AS total_bytes FROM apiome.mock_session ORDER BY session_token",
    );
    expect(sessions.rows).toEqual([{ session_token: "live", resource_count: 2, total_bytes: 16 }]);
    const resources = await client.query("SELECT resource_id FROM apiome.mock_session_resource ORDER BY resource_id");
    expect(resources.rows.map((row) => row.resource_id)).toEqual(["1", "2"]);
    expect(await slotCount()).toBe(1);
    const old = await client.query("SELECT to_regclass('apiome.mock_session_state') AS t");
    expect(old.rows[0].t).toBeNull();
  });
});
