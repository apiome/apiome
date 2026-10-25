/**
 * Structural assertions over V320: the per-user Suite Access switch that apiome-ui reads before it
 * shows the Designer and Developer suites (`apiome-ui/lib/db/commercial-access.ts`).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V320__users_suite_access.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n")
    .replace(/\s+/g, " ");
});

describe("users suite access (V320)", () => {
  it("is present in scripts/ and ordered after V319", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V319__release_deleted_user_identities.sql"),
    );
  });

  it("adds a per-user switch that starts off for every account", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain(
      "alter table apiome.users add column if not exists suite_access boolean not null default false",
    );
  });

  it("grants no one suite access", () => {
    expect(statements).not.toMatch(/update apiome\.users/);
    expect(statements).not.toMatch(/insert into/);
  });
});
