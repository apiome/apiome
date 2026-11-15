/**
 * Structural assertions over the index hygiene migration (V381).
 *
 * V381 drops indexes another index already covers and adds the ones cascade deletes and a few list
 * queries were missing. The promises pinned here are the safety ones: every statement is
 * idempotent (so an operator can pre-build the indexes concurrently), nothing but an index is
 * touched, and no index is both created and dropped.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V381__index_hygiene_and_cascade_indexes.sql";

let statements: string[] = [];

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .split(";")
    .map((statement) => statement.replace(/\s+/g, " ").trim())
    .filter(Boolean);
});

function names(pattern: RegExp): string[] {
  return statements.flatMap((statement) => {
    const match = pattern.exec(statement);
    return match ? [match[1]] : [];
  });
}

describe("index hygiene migration", () => {
  it("is ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V380__usage_sdk_beacon_rdg_1_7.sql"));
  });

  it("only drops and creates indexes, idempotently", () => {
    for (const statement of statements) {
      expect(statement).toMatch(/^(drop index if exists apiome\.\w+|create index if not exists \w+ on apiome\.\w+ \()/);
    }
  });

  it("never creates a unique index or builds concurrently", () => {
    for (const statement of statements) {
      expect(statement).not.toMatch(/unique|concurrently/);
    }
  });

  it("does not drop an index it creates", () => {
    const dropped = new Set(names(/^drop index if exists apiome\.(\w+)/));
    const created = names(/^create index if not exists (\w+)/);
    expect(dropped.size).toBe(85);
    expect(created.length).toBe(98);
    expect(new Set(created).size).toBe(created.length);
    for (const name of created) {
      expect(dropped.has(name)).toBe(false);
      expect(name.length).toBeLessThanOrEqual(63);
    }
  });

  it("drops the index that blocked HOT updates of api_keys.last_used_at", () => {
    expect(statements).toContain("drop index if exists apiome.idx_api_keys_last_used_at");
  });
});
