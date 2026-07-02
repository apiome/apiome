import { describe, expect, it } from "vitest";

import {
  computeChecksum,
  isMigrationFilename,
  listMigrationFiles,
  parseMigrationName,
} from "../src/migrate.js";

describe("isMigrationFilename", () => {
  it("accepts Flyway versioned scripts", () => {
    expect(isMigrationFilename("V001__multitenant_init.sql")).toBe(true);
    expect(isMigrationFilename("V117__rename_thing.sql")).toBe(true);
  });

  it("rejects non-migration / SEM-style files", () => {
    expect(isMigrationFilename("test_foo.sql")).toBe(false);
    expect(isMigrationFilename("20251026-012616.sql")).toBe(false); // old SEM name
    expect(isMigrationFilename("V001.sql")).toBe(false); // missing __description
    expect(isMigrationFilename("R__repeatable.sql")).toBe(false); // repeatable unsupported
  });
});

describe("parseMigrationName", () => {
  it("splits the version and description", () => {
    expect(parseMigrationName("V001__multitenant_init.sql")).toEqual({
      version: "001",
      description: "multitenant init",
    });
  });

  it("supports dotted/underscored version parts", () => {
    expect(parseMigrationName("V1_2_3__thing.sql").version).toBe("1_2_3");
    expect(parseMigrationName("V1.2.3__thing.sql").version).toBe("1.2.3");
  });
});

describe("computeChecksum", () => {
  it("is stable for identical content", () => {
    expect(computeChecksum("CREATE TABLE foo (id int);")).toBe(
      computeChecksum("CREATE TABLE foo (id int);"),
    );
  });

  it("ignores CRLF vs LF line endings", () => {
    expect(computeChecksum("a\r\nb\r\nc")).toBe(computeChecksum("a\nb\nc"));
  });

  it("changes when the content changes", () => {
    expect(computeChecksum("CREATE TABLE foo (id int);")).not.toBe(
      computeChecksum("CREATE TABLE bar (id int);"),
    );
  });

  it("returns a signed 32-bit integer", () => {
    const sum = computeChecksum("some migration sql");
    expect(Number.isInteger(sum)).toBe(true);
    expect(sum).toBeGreaterThanOrEqual(-(2 ** 31));
    expect(sum).toBeLessThanOrEqual(2 ** 31 - 1);
  });
});

describe("listMigrationFiles", () => {
  it("returns sorted Flyway migration filenames from scripts/", async () => {
    const files = await listMigrationFiles(new URL("../scripts", import.meta.url).pathname);
    expect(files.length).toBeGreaterThan(50);
    expect(files[0]).toMatch(/^V\d+__.+\.sql$/);
    const sorted = [...files].sort();
    expect(files).toEqual(sorted);
  });
});
