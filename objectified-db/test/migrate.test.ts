import { describe, expect, it } from "vitest";

import {
  isMigrationFilename,
  listMigrationFiles,
  parseTransactionMode,
} from "../src/migrate.js";

describe("isMigrationFilename", () => {
  it("accepts timestamped migration scripts", () => {
    expect(isMigrationFilename("20251026-012616.sql")).toBe(true);
    expect(isMigrationFilename("20260511-162000.sql")).toBe(true);
  });

  it("rejects non-migration files", () => {
    expect(isMigrationFilename("test_foo.sql")).toBe(false);
    expect(isMigrationFilename("20251026.sql")).toBe(false);
  });
});

describe("parseTransactionMode", () => {
  it("defaults to single transaction", () => {
    expect(parseTransactionMode("CREATE TABLE foo (id int);")).toBe("single");
  });

  it("reads sem transaction attribute", () => {
    const sql = `-- sem.attribute.transaction = none\nCREATE INDEX CONCURRENTLY idx ON foo (id);`;
    expect(parseTransactionMode(sql)).toBe("none");
  });
});

describe("listMigrationFiles", () => {
  it("returns sorted migration filenames from scripts/", async () => {
    const files = await listMigrationFiles(new URL("../scripts", import.meta.url).pathname);
    expect(files.length).toBeGreaterThan(50);
    expect(files[0]).toMatch(/^\d{8}-\d{6}\.sql$/);
    const sorted = [...files].sort();
    expect(files).toEqual(sorted);
  });
});
