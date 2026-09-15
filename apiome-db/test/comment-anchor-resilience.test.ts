/**
 * Structural assertions over the comment anchor resilience migration (#4516, COL-1.4).
 *
 * V259 anchors a comment thread to an element by primary key, which already makes a thread survive
 * a rename or a move. V260 decides what happens when the element is **deleted**:
 *
 *   1. **The thread is orphaned, not lost** — `status` gains `orphaned`, with the element's
 *      last-known `anchor_label` and `orphaned_at` set exactly while orphaned.
 *   2. **Every writer orphans** — triggers on the soft delete of classes and library properties and
 *      on the hard delete of class properties, paths, and operations (FK cascades included).
 *   3. **A rename never orphans** — no trigger watches a name column, and the soft-delete triggers
 *      fire only on the transition to deleted.
 *   4. **A relink can restore resolution** — an orphaned thread keeps `resolved_at`.
 *
 * These must stay in lock-step with apiome-rest's `app.comments` vocabulary and its
 * `tests/test_comment_anchor_resilience_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V260__comment_anchor_resilience_4516.sql";

let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/**
 * The body of one plpgsql trigger function.
 *
 * @param name - The function name without its schema.
 * @returns The text between the function's `$$` quotes.
 */
function functionBody(name: string): string {
  const start = statements.indexOf(`function apiome.${name}()`);
  expect(start).toBeGreaterThan(-1);
  const open = statements.indexOf("$$", start);
  const close = statements.indexOf("$$", open + 2);
  return statements.slice(open + 2, close);
}

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  statements = lower
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("comment anchor resilience migration", () => {
  it("is present in scripts/ and ordered after the comment threads migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V259__comment_threads_4513.sql"));
  });

  it("targets the apiome schema and alters comment_threads idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(statements).toContain("alter table comment_threads add column if not exists anchor_label varchar(512)");
    expect(statements).toContain(
      "alter table comment_threads add column if not exists orphaned_at timestamp with time zone",
    );
    for (const constraint of [
      "comment_threads_status_check",
      "comment_threads_resolution_check",
      "comment_threads_orphan_check",
    ]) {
      expect(statements).toContain(`drop constraint if exists ${constraint}`);
    }
  });

  describe("rule 1 — orphaned, not lost", () => {
    it("widens the status vocabulary", () => {
      expect(statements).toContain("check (status in ('open', 'resolved', 'orphaned'))");
    });

    it("carries a label and a time exactly while orphaned, never on a version anchor", () => {
      expect(statements).toContain("(status = 'orphaned') = (orphaned_at is not null)");
      expect(statements).toContain("(status = 'orphaned') = (anchor_label is not null)");
      expect(statements).toContain("(status <> 'orphaned' or anchor_type <> 'version')");
    });

    it("never writes a null label", () => {
      const helper = statements.slice(statements.indexOf("function apiome.orphan_comment_threads("));
      expect(helper).toContain("coalesce(nullif(btrim(p_label), ''), p_anchor_type || ' ' || p_anchor_id::text)");
    });
  });

  describe("rule 2 — every writer orphans", () => {
    it.each([
      ["after update of deleted_at on apiome.classes", "comment_threads_orphan_class"],
      ["before delete on apiome.classes", "comment_threads_orphan_class"],
      ["before delete on apiome.class_properties", "comment_threads_orphan_class_property"],
      ["after update of deleted_at on apiome.properties", "comment_threads_orphan_property"],
      ["before delete on apiome.properties", "comment_threads_orphan_property"],
      ["before delete on apiome.version_path", "comment_threads_orphan_path"],
      ["before delete on apiome.path_operation", "comment_threads_orphan_operation"],
    ])("fires %s", (event, fn) => {
      const at = statements.indexOf(event);
      expect(at).toBeGreaterThan(-1);
      expect(statements.slice(at, statements.indexOf(";", at))).toContain(`execute function apiome.${fn}()`);
    });

    it("orphans a deleted class's property threads and a deleted path's operation threads", () => {
      expect(functionBody("comment_threads_orphan_class")).toContain("from apiome.class_properties cp");
      expect(functionBody("comment_threads_orphan_path")).toContain("from apiome.path_operation po");
    });

    it("returns the deleted row from every trigger, so no delete is cancelled", () => {
      for (const fn of [
        "comment_threads_orphan_class",
        "comment_threads_orphan_class_property",
        "comment_threads_orphan_property",
        "comment_threads_orphan_path",
        "comment_threads_orphan_operation",
      ]) {
        const body = functionBody(fn);
        expect(body).toContain("return old;");
        expect(body).not.toContain("return null");
      }
    });

    it("indexes the live-thread lookup the triggers make", () => {
      expect(statements).toContain("on comment_threads (anchor_id) where status <> 'orphaned'");
    });
  });

  describe("rule 3 — a rename never orphans", () => {
    it("watches only deletes and the deleted_at column", () => {
      const events = [...statements.matchAll(/create trigger \w+\s+(?:before|after) (.+?) on apiome\./g)].map(
        (match) => match[1],
      );
      expect(events).toHaveLength(7);
      for (const event of events) {
        expect(["delete", "update of deleted_at"]).toContain(event);
      }
    });

    it("fires the soft-delete triggers only on the transition to deleted", () => {
      expect(statements.match(/when \(old\.deleted_at is null and new\.deleted_at is not null\)/g)).toHaveLength(2);
    });
  });

  describe("rule 4 — a relink can restore resolution", () => {
    it("lets an orphaned thread keep resolved_at", () => {
      expect(statements).toContain(
        "check (status = 'orphaned' or (status = 'resolved') = (resolved_at is not null))",
      );
    });
  });

  it("changes no RBAC grid, drops no table, and defines no enum types", () => {
    expect(statements).not.toContain("seed_builtin_roles");
    expect(statements).not.toContain("role_permissions");
    expect(statements).not.toContain("drop table");
    expect(statements).not.toContain("create type");
  });
});
