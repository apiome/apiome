/**
 * Foreign-key index coverage (DBP-1.12, #7195).
 *
 * Three layers:
 *   1. The coverage rules in `src/lib/fk-index-coverage.ts` (which partial predicates the
 *      referential check can use), as unit tests.
 *   2. Structural promises of V418 (idempotent, index-only, nothing both created and dropped) and
 *      the shape of the reviewed allowlist.
 *   3. The schema test proper: on a migrated database, the foreign keys without a usable index
 *      must be exactly the allowlisted ones. A migration that adds an unindexed foreign key fails
 *      here, and so does an allowlist entry that is now indexed or gone.
 *
 * Layer 3 needs `APIOME_DB_SCHEMA_TEST_URL` pointing at a database migrated to the current head
 * (CI's `schema` job in .github/workflows/apiome-db.yml starts one); without it that block is
 * skipped. Locally:
 *
 *     createdb apiome_fk && node dist/cli.js migrate --database-url postgresql://localhost/apiome_fk
 *     APIOME_DB_SCHEMA_TEST_URL=postgresql://localhost/apiome_fk yarn vitest run test/foreign-key-index-coverage.test.ts
 */

import fs from "node:fs/promises";
import path from "node:path";

import pg from "pg";
import { beforeAll, describe, expect, it } from "vitest";

import {
  listUncoveredForeignKeys,
  predicateServesForeignKey,
  uncoveredForeignKeys,
  type ForeignKeyRow,
} from "../src/lib/fk-index-coverage.js";
import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const ALLOWLIST_FILE = new URL("./foreign-key-index-allowlist.json", import.meta.url).pathname;
const MIGRATION = "V418__foreign_key_indexes_7195.sql";
const SCHEMA_TEST_URL = process.env.APIOME_DB_SCHEMA_TEST_URL?.trim() ?? "";

type Allowlist = { description: string; reasons: Record<string, string>; foreignKeys: Record<string, string> };

async function readAllowlist(): Promise<Allowlist> {
  return JSON.parse(await fs.readFile(ALLOWLIST_FILE, "utf8")) as Allowlist;
}

/** A catalog row with one candidate index, for the classification tests. */
function fk(columns: string[], indexes: ForeignKeyRow["candidateIndexes"]): ForeignKeyRow {
  return { table: "child", constraint: "child_fk", columns, referencedTable: "parent", candidateIndexes: indexes };
}

describe("predicateServesForeignKey", () => {
  it("accepts a non-partial index", () => {
    expect(predicateServesForeignKey(null, ["version_id"])).toBe(true);
  });

  it("accepts IS NOT NULL on a foreign-key column, alone or in a conjunction", () => {
    expect(predicateServesForeignKey("(release_id IS NOT NULL)", ["release_id"])).toBe(true);
    expect(predicateServesForeignKey("((a IS NOT NULL) AND (b IS NOT NULL))", ["a", "b"])).toBe(true);
    expect(predicateServesForeignKey("(a IS NOT NULL)", ["a", "b"])).toBe(true);
  });

  it("rejects predicates the referential check cannot prove", () => {
    expect(predicateServesForeignKey("(deleted_at IS NULL)", ["version_id"])).toBe(false);
    expect(predicateServesForeignKey("(project_id IS NOT NULL)", ["tenant_id"])).toBe(false);
    expect(predicateServesForeignKey("((a IS NOT NULL) AND (deleted_at IS NULL))", ["a"])).toBe(false);
    expect(predicateServesForeignKey("((status)::text = 'pending'::text)", ["status"])).toBe(false);
    expect(predicateServesForeignKey("(a IS NULL)", ["a"])).toBe(false);
  });

  it("does not strip parentheses that do not enclose the whole expression", () => {
    expect(predicateServesForeignKey("(a IS NOT NULL) OR (b IS NOT NULL)", ["a", "b"])).toBe(false);
  });
});

describe("uncoveredForeignKeys", () => {
  const btree = (predicate: string | null, valid = true) => ({ name: "i", predicate, method: "btree", valid });

  it("passes a foreign key with a usable b-tree", () => {
    expect(uncoveredForeignKeys([fk(["a"], [btree(null)])])).toEqual([]);
    expect(uncoveredForeignKeys([fk(["a"], [btree("(deleted_at IS NULL)"), btree("(a IS NOT NULL)")])])).toEqual([]);
  });

  it("reports none when no index starts with the columns", () => {
    expect(uncoveredForeignKeys([fk(["a"], [])])).toMatchObject([{ key: "child.child_fk", status: "none" }]);
  });

  it("reports partial when only unusable, invalid or non-b-tree indexes do", () => {
    const rows = [
      fk(["a"], [btree("(deleted_at IS NULL)")]),
      fk(["a"], [btree(null, false)]),
      fk(["a"], [{ name: "g", predicate: null, method: "gin", valid: true }]),
    ];
    expect(uncoveredForeignKeys(rows).map((row) => row.status)).toEqual(["partial", "partial", "partial"]);
  });
});

describe("foreign-key index migration (V418)", () => {
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

  const names = (pattern: RegExp): string[] =>
    statements.flatMap((statement) => {
      const match = pattern.exec(statement);
      return match?.[1] ? [match[1]] : [];
    });

  it("is ordered after the DBP-1.11 indexes", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V417__auth_and_log_indexes_7194.sql"));
  });

  it("only creates and drops non-unique indexes, idempotently and without CONCURRENTLY", () => {
    for (const statement of statements) {
      expect(statement).toMatch(/^(drop index if exists apiome\.\w+|create index if not exists \w+ on apiome\.\w+ \()/);
      expect(statement).not.toMatch(/unique|concurrently/);
    }
  });

  it("creates 166 foreign-key indexes, replaces 31, and never drops one it creates", () => {
    const created = names(/^create index if not exists (\w+)/);
    const dropped = new Set(names(/^drop index if exists apiome\.(\w+)/));
    expect(created).toHaveLength(166);
    expect(new Set(created).size).toBe(created.length);
    expect(dropped.size).toBe(31);
    for (const name of created) {
      expect(dropped.has(name)).toBe(false);
      expect(name.length).toBeLessThanOrEqual(63);
    }
  });

  it("only uses IS NOT NULL partial predicates, which the referential check can use", () => {
    for (const statement of statements.filter((s) => s.includes(" where "))) {
      const predicate = statement.split(" where ")[1] ?? "";
      for (const term of predicate.split(" and ")) expect(term.trim()).toMatch(/^\w+ is not null$/);
    }
  });

  it("replaces the partial index the version-delete check could not use", () => {
    expect(statements).toContain("create index if not exists idx_classes_version_id_fk on apiome.classes (version_id)");
    expect(statements).toContain("drop index if exists apiome.idx_classes_version_id");
  });
});

describe("foreign-key index allowlist", () => {
  it("gives every entry a known reason and keeps the keys sorted", async () => {
    const allowlist = await readAllowlist();
    const keys = Object.keys(allowlist.foreignKeys);
    expect(keys).toEqual([...keys].sort());
    for (const [key, reason] of Object.entries(allowlist.foreignKeys)) {
      expect(key).toMatch(/^\w+\.\w+$/);
      expect(Object.keys(allowlist.reasons)).toContain(reason);
    }
  });
});

describe.skipIf(SCHEMA_TEST_URL === "")("foreign-key index coverage on the migrated schema", () => {
  it("leaves exactly the allowlisted foreign keys without a usable index", async () => {
    const client = new pg.Client({ connectionString: SCHEMA_TEST_URL });
    await client.connect();
    try {
      const uncovered = await listUncoveredForeignKeys(client);
      const allowed = new Set(Object.keys((await readAllowlist()).foreignKeys));
      const found = new Set(uncovered.map((row) => row.key));

      const unlisted = uncovered
        .filter((row) => !allowed.has(row.key))
        .map((row) => `${row.key} (${row.columns.join(", ")} -> ${row.referencedTable}, ${row.status})`);
      const stale = [...allowed].filter((key) => !found.has(key));

      // A new foreign key needs an index led by its columns (WHERE <col> IS NOT NULL for a sparse
      // nullable column) or, with a reason, an entry in test/foreign-key-index-allowlist.json.
      expect(unlisted, "foreign keys with no usable index").toEqual([]);
      // An entry whose foreign key is now indexed (or was dropped) must leave the allowlist.
      expect(stale, "allowlist entries that are indexed or no longer exist").toEqual([]);
    } finally {
      await client.end();
    }
  });
});
