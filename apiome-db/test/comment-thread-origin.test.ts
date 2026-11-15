/**
 * Structural assertions over the comment thread origin migration (#4528, COL-4.4).
 *
 * V379 tags each comment thread with where it came from — `internal` (workspace members, every
 * thread before it) or `consumer` (feedback a Browse reader opened). Must stay in lock-step with
 * apiome-rest's `app.comments` origin vocabulary.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V379__comment_thread_origin_col_4_4.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("comment thread origin migration", () => {
  it("is ordered after the reader identity migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V378__portal_reader_identity_pcx_1_1.sql"));
  });

  it("adds an origin column that defaults existing threads to internal", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain(
      "alter table comment_threads add column if not exists origin varchar(16) not null default 'internal'",
    );
  });

  it("closes the vocabulary with a check constraint", () => {
    expect(statements).toContain("check (origin in ('internal', 'consumer'))");
    expect(statements).not.toContain("create type");
  });

  it("indexes the Origin filter and the reader's own-thread read", () => {
    expect(statements).toContain("on comment_threads (project_id, origin)");
    expect(statements).toMatch(/on comment_threads \(version_id, created_by\)\s+where origin = 'consumer'/);
  });
});
