/**
 * Structural assertions over the mock broker publish usage migration (#5736, XPC-2.2).
 *
 * V373 adds `apiome.mock_event_publish_usage` — daily counts of events the hosted mock published to
 * a bound broker, per channel, encoding and trigger, plus records refused for failing their schema —
 * and `apiome.record_mock_event_publish(...)`, the upsert the mock calls. Metadata only.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V373__mock_event_publish_usage_xpc_2_2.sql";

let sql = "";
let lower = "";
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?;/g, "")
    .toLowerCase();
});

describe("mock event publish usage migration", () => {
  it("is ordered after the XPC-2.1 broker bindings migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V372__mock_broker_bindings_xpc_2_1.sql"),
    );
  });

  it("creates the rollup idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toContain("create table if not exists mock_event_publish_usage (");
    expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
  });

  it("keys one row per tenant, version, channel, encoding, trigger and day", () => {
    expect(lower).toContain(
      "primary key (tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date)",
    );
    expect(sql).toContain("CHECK (encoding IN ('json', 'avro', 'protobuf'))");
    expect(sql).toContain("CHECK (trigger IN ('periodic', 'on-demand'))");
  });

  it("counts published and refused records, never negative", () => {
    expect(lower).toContain("published_count bigint not null default 0 check (published_count >= 0)");
    expect(lower).toContain("rejected_count bigint not null default 0 check (rejected_count >= 0)");
  });

  it("upserts through record_mock_event_publish", () => {
    expect(lower).toContain("create or replace function apiome.record_mock_event_publish(");
    expect(lower).toContain("on conflict (tenant_id, project_slug, version_label, channel_key, encoding, trigger, usage_date)");
  });

  it("stores no payload, key, header or topic data", () => {
    const start = ddl.indexOf("create table if not exists mock_event_publish_usage (");
    const body = ddl.slice(start, ddl.indexOf("\n);", start));
    for (const column of ["payload", "header", "topic", "value", "key bytea", "body"]) {
      expect(body).not.toContain(column);
    }
  });
});
