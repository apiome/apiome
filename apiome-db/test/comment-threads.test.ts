/**
 * Structural assertions over the comment threads migration (#4513, COL-1.1).
 *
 * V259 adds `apiome.comment_threads` and `apiome.comments` — the storage every collaboration item
 * builds on (Studio thread UI, Discussion panel, anchor resilience, notifications, reviews).
 *
 * DB-free contract tests pin the migration shape, concentrating on the five rules the ticket's
 * scope turns into schema rather than habit:
 *
 *   1. **Threads anchor by stable element id, never by coordinates** — a closed `anchor_type`
 *      vocabulary plus a UUID `anchor_id`, with no x/y column anywhere.
 *   2. **A version anchor is the thread's own version.**
 *   3. **Status is `open | resolved`, and resolution is recorded exactly when resolved.**
 *   4. **Mentions are server-resolved user ids** — `uuid[]`, capped, GIN indexed.
 *   5. **Scope cascades from tenant/project/version; deleting a user keeps their words.**
 *
 * There is deliberately **no RBAC change**: read access to a project grants commenting, and
 * author-or-admin ownership is enforced in apiome-rest.
 *
 * These must stay in lock-step with apiome-rest's `app.comments` vocabulary and its
 * `tests/test_comment_threads_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V259__comment_threads_4513.sql";
const THREADS = "comment_threads";
const COMMENTS = "comments";

let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** The statements of one table's CREATE block (up to the next CREATE TABLE). */
function tableSection(table: string): string {
  const start = statements.indexOf(`create table if not exists ${table} (`);
  const next = statements.indexOf("create table if not exists", start + 1);
  return statements.slice(start, next === -1 ? undefined : next);
}

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  statements = lower
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("comment threads migration", () => {
  it("is present in scripts/ and ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V258__sdk_regen_on_publish_4497.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    for (const table of [THREADS, COMMENTS]) {
      expect(statements).toMatch(new RegExp(`create table if not exists ${table} \\(`));
    }
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(statements).toContain("uuid_generate_v4()");
    expect(statements).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — anchored by stable element id", () => {
    it("constrains the element vocabulary and stores a uuid anchor", () => {
      const section = tableSection(THREADS);
      expect(section).toContain(
        "check (anchor_type in ('class', 'property', 'path', 'operation', 'version'))",
      );
      expect(section).toContain("anchor_id uuid not null");
    });

    it("stores no canvas coordinates", () => {
      // Only the column list: the COMMENT ON strings after it legitimately say "never coordinates".
      const columns = tableSection(THREADS).split("\n);")[0];
      for (const column of ["position", " x ", " y ", "coordinates"]) {
        expect(columns).not.toContain(column);
      }
    });

    it("indexes the per-element read the Studio badges use", () => {
      expect(statements).toContain(`on ${THREADS} (version_id, anchor_type, anchor_id)`);
    });
  });

  describe("rule 2 — a version anchor is the version itself", () => {
    it("ties a version anchor to version_id", () => {
      expect(tableSection(THREADS)).toContain("check (anchor_type <> 'version' or anchor_id = version_id)");
    });
  });

  describe("rule 3 — status with a recorded resolution", () => {
    it("is open or resolved, defaulting to open", () => {
      const section = tableSection(THREADS);
      expect(section).toContain("status varchar(16) not null default 'open'");
      expect(section).toContain("check (status in ('open', 'resolved'))");
    });

    it("carries resolved_at exactly when resolved", () => {
      expect(tableSection(THREADS)).toContain("check ((status = 'resolved') = (resolved_at is not null))");
    });

    it("indexes the project list read and the status filter", () => {
      expect(statements).toContain(`on ${THREADS} (project_id, last_activity_at desc)`);
      expect(statements).toContain(`on ${THREADS} (project_id, status)`);
    });
  });

  describe("rule 4 — server-resolved mentions", () => {
    it("stores mentions as a capped uuid array", () => {
      const section = tableSection(COMMENTS);
      expect(section).toContain("mentions uuid[] not null default array[]::uuid[]");
      expect(section).toContain("check (cardinality(mentions) <= 50)");
    });

    it("indexes mentions for containment queries", () => {
      expect(statements).toContain(`on ${COMMENTS} using gin (mentions)`);
    });

    it("bounds the markdown body and records edits", () => {
      const section = tableSection(COMMENTS);
      expect(section).toContain("check (length(btrim(body)) > 0 and length(body) <= 20000)");
      expect(section).toContain("edited_at timestamp with time zone,");
    });
  });

  describe("rule 5 — scope and ownership", () => {
    it("cascades a thread from its tenant, project, and version", () => {
      const section = tableSection(THREADS);
      expect(section).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(section).toContain("project_id uuid not null references projects(id) on delete cascade");
      expect(section).toContain("version_id uuid not null references versions(id) on delete cascade");
    });

    it("cascades comments from their thread but keeps them when a user is deleted", () => {
      const section = tableSection(COMMENTS);
      expect(section).toContain(`thread_id uuid not null references ${THREADS}(id) on delete cascade`);
      expect(section).toContain("author_id uuid references users(id) on delete set null");
      expect(tableSection(THREADS)).toContain("created_by uuid references users(id) on delete set null");
    });
  });

  it("changes no RBAC grid and defines no enum types", () => {
    expect(statements).not.toContain("seed_builtin_roles");
    expect(statements).not.toContain("role_permissions");
    expect(statements).not.toContain("create type");
  });
});
