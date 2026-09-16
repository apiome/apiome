/**
 * Structural assertions over the notification inbox migration (#4521, COL-3.1).
 *
 * V263 adds `apiome.notifications` — one row per recipient per collaboration event, written in the
 * same transaction as the event itself. The notification centre (COL-3.2) reads it, and the email
 * (COL-3.3) and Slack/Teams (COL-3.4) workers will later fan the same rows out.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's scope
 * turns into schema rather than habit:
 *
 *   1. **One row per recipient** — `user_id` is NOT NULL and the inbox reads are per user.
 *   2. **A closed type vocabulary** — five strings, as a CHECK rather than an ENUM.
 *   3. **`read_at` NULL means unread** — the unread badge counts exactly those, and there is a
 *      partial index for it.
 *   4. **The inbox is capped by the database** — a statement-level trigger prunes past the newest
 *      500 rows of every user an insert touched.
 *   5. **Marking read is the only mutation** — a trigger refuses every other change.
 *   6. **Scope cascades from tenant, recipient, project, and version; the actor survives.**
 *
 * There is deliberately **no RBAC change**: an inbox is the caller's own, and apiome-rest scopes it.
 * These must stay in lock-step with apiome-rest's `app.notifications` vocabulary and its
 * `tests/test_notifications_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V263__notifications_col_3_1.sql";
const TABLE = "notifications";

/** The five notification types, in the order the migration lists them. */
const TYPES = [
  "mention",
  "review_requested",
  "review_decision",
  "thread_resolved",
  "version_published",
];

let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** The table's column block: from its CREATE TABLE to the closing `);`. */
function tableBlock(table: string): string {
  const start = statements.indexOf(`create table if not exists ${table} (`);
  const end = statements.indexOf("\n);", start);
  return statements.slice(start, end);
}

/** One trigger function's body: from its CREATE FUNCTION to its `$$ language plpgsql`. */
function functionBody(name: string): string {
  const start = statements.indexOf(`create or replace function apiome.${name}()`);
  const end = statements.indexOf("$$ language plpgsql", start);
  return statements.slice(start, end);
}

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  statements = lower
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("notifications migration", () => {
  it("is present in scripts/ and ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V262__approval_publish_policy_col_2_3.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(statements).toMatch(new RegExp(`create table if not exists ${TABLE} \\(`));
  });

  it("stores one row per recipient, in one tenant", () => {
    const block = tableBlock(TABLE);
    expect(block).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(block).toContain("user_id uuid not null references users(id) on delete cascade");
  });

  it("stores only the five event types, as a check and not an enum", () => {
    const block = tableBlock(TABLE);
    expect(block).toContain("type varchar(32) not null");
    for (const type of TYPES) {
      expect(block).toContain(`'${type}'`);
    }
    expect(statements).not.toContain("create type");
  });

  it("keeps the payload a JSON object", () => {
    const block = tableBlock(TABLE);
    expect(block).toContain("payload jsonb not null default '{}'::jsonb");
    expect(block).toContain("check (jsonb_typeof(payload) = 'object')");
  });

  it("marks unread with a null read_at and indexes exactly those rows", () => {
    expect(tableBlock(TABLE)).toContain("read_at timestamp with time zone");
    expect(statements).toMatch(
      /create index if not exists idx_notifications_user_unread\s+on notifications \(user_id, type\) where read_at is null/,
    );
  });

  it("indexes the inbox read newest first", () => {
    expect(statements).toMatch(
      /create index if not exists idx_notifications_user_created\s+on notifications \(user_id, created_at desc, id desc\)/,
    );
    expect(statements).toMatch(
      /create index if not exists idx_notifications_tenant\s+on notifications \(tenant_id\)/,
    );
  });

  it("caps each inbox at 500 rows with one statement-level trigger", () => {
    const prune = functionBody("notifications_enforce_retention");
    expect(prune).toContain("retention_cap constant integer := 500");
    expect(prune).toContain("partition by n.user_id order by n.created_at desc, n.id desc");
    expect(prune).toContain("where ranked.position > retention_cap");
    expect(prune).toContain("select distinct i.user_id from inserted i");
    expect(statements).toMatch(
      /create trigger trg_notifications_enforce_retention\s+after insert on notifications\s+referencing new table as inserted\s+for each statement\s+execute function apiome\.notifications_enforce_retention\(\)/,
    );
  });

  it("lets nothing but read_at change once a row is written", () => {
    const guard = functionBody("notifications_guard_immutable");
    for (const column of ["tenant_id", "user_id", "type", "payload", "project_id", "version_id", "created_at"]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    expect(guard).not.toContain("new.read_at is distinct from old.read_at");
    expect(statements).toMatch(
      /create trigger trg_notifications_guard_immutable\s+before update on notifications\s+for each row\s+execute function apiome\.notifications_guard_immutable\(\)/,
    );
  });

  it("cascades from tenant, recipient, project, and version but keeps a departed actor's event", () => {
    const block = tableBlock(TABLE);
    expect(block).toContain("project_id uuid references projects(id) on delete cascade");
    expect(block).toContain("version_id uuid references versions(id) on delete cascade");
    expect(block).toContain("actor_id uuid references users(id) on delete set null");
    expect(functionBody("notifications_guard_immutable")).toContain(
      "(new.actor_id is distinct from old.actor_id and new.actor_id is not null)",
    );
  });

  it("changes no RBAC and stores no delivery preferences yet", () => {
    expect(statements).not.toContain("seed_builtin_roles");
    expect(statements).not.toContain("role_permissions");
    expect(statements).not.toContain("notification_preferences");
  });
});
