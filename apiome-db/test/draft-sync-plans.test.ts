/**
 * Structural assertions over the three-way synchronization migration (#4739, GNC-2.3).
 *
 * V266 adds `apiome.draft_sync_plans` — one semantic three-way merge of a bound draft against its
 * repository ref, recording the base, Git and draft digests it was computed from — and
 * `apiome.draft_sync_conflicts`, one row per overlapping change carrying all three sides with the
 * place in the repository source it lives at. V264 (GNC-2.1) supplies the binding a plan hangs off
 * and the sync candidate that prompts one.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's
 * acceptance criteria turn into schema rather than habit:
 *
 *   1. **A plan is a reading, never a write** — nothing here gives a provider delivery a path to a
 *      draft, which is what "an active draft or review decision is never overwritten" means once it
 *      reaches storage.
 *   2. **A plan is identified by the three documents it merged** — unique on (binding,
 *      plan_fingerprint), which is what makes a rerun idempotent.
 *   3. **All three digests are recorded** — base, Git and draft, the acceptance criterion literally.
 *   4. **A conflict names a place, not just a value** — pointer, scope/group, file and line.
 *   5. **A settlement is final** — a conflict is resolved once, towards `git` or `draft`.
 *
 * There is deliberately **no RBAC change**: computing a merge needs `versions:edit` plus an active
 * binding, which apiome-rest enforces. These must stay in lock-step with apiome-rest's
 * `app.spec_sync` vocabulary and its `tests/test_spec_sync_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V266__draft_sync_plans_gnc_2_3.sql";
const PLANS = "draft_sync_plans";
const CONFLICTS = "draft_sync_conflicts";

/** The four merge outcomes, in the order the migration lists them. */
const PLAN_STATUSES = ["clean", "mergeable", "conflicted", "resolved"];

/** Why a merge result may not become an edit of the draft. */
const PLAN_GUARDS = ["none", "review_decided", "version_published"];

/** The grouping vocabulary `app.source_change_review.scope_for_pointer` speaks. */
const CONFLICT_SCOPES = ["document", "path", "operation", "component", "schema"];

/** What each side did to the base at a conflicting pointer. */
const CHANGE_KINDS = ["addition", "update", "deletion"];

/** The two sides a conflict can be settled towards. */
const RESOLUTIONS = ["git", "draft"];

/** Words that must never name a column of either table — a merge holds no credential. */
const CREDENTIAL_WORDS = ["token", "secret", "credential", "ciphertext", "password"];

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

describe("draft sync plan migration", () => {
  it("is present in scripts/ and ordered after the binding migration it builds on", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V264__draft_repository_bindings_gnc_2_1.sql"),
    );
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V265__provider_check_runs_gnc_2_2.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(statements).toMatch(new RegExp(`create table if not exists ${PLANS} \\(`));
    expect(statements).toMatch(new RegExp(`create table if not exists ${CONFLICTS} \\(`));
  });

  // -- Rule 1 ---------------------------------------------------------------------------------

  it("gives a merge result no way to edit a draft", () => {
    // The whole safety property of the ticket, as schema: these tables reference the version they
    // describe and nothing else, and no statement in the migration writes to any other table.
    expect(statements).not.toMatch(/update\s+versions/);
    expect(statements).not.toMatch(/insert\s+into\s+versions/);
    expect(statements).not.toMatch(/update\s+apiome\.versions/);
    // No column claims a draft was changed, because none ever is here.
    expect(tableBlock(PLANS)).not.toContain("applied_at");
  });

  it("records why a result may not become an edit, as it stood when the merge ran", () => {
    const block = tableBlock(PLANS);
    expect(block).toContain("guard varchar(32) not null default 'none'");
    expect(block).toContain(`check (guard in (${PLAN_GUARDS.map((g) => `'${g}'`).join(", ")}))`);
  });

  it("hangs a plan off its binding and removes it with the binding", () => {
    const block = tableBlock(PLANS);
    expect(block).toContain(
      "binding_id uuid not null references draft_repository_bindings(id) on delete cascade",
    );
    expect(block).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(block).toContain("project_id uuid not null references projects(id) on delete cascade");
    expect(block).toContain("version_id uuid not null references versions(id) on delete cascade");
    // The merge result outlives the notification that prompted it, and the person who ran it.
    expect(block).toContain(
      "candidate_id uuid references draft_binding_sync_candidates(id) on delete set null",
    );
    expect(block).toContain("computed_by uuid references users(id) on delete set null");
  });

  // -- Rule 2 ---------------------------------------------------------------------------------

  it("identifies a plan by the binding and the three documents it merged", () => {
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_draft_sync_plans_fingerprint\\s+on ${PLANS} \\(binding_id, plan_fingerprint\\)`,
      ),
    );
    expect(tableBlock(PLANS)).toContain("plan_fingerprint varchar(128) not null");
  });

  it("freezes what a merge was computed from while letting its outcome move", () => {
    const guard = functionBody("draft_sync_plans_guard_identity");
    for (const column of [
      "tenant_id",
      "binding_id",
      "project_id",
      "version_id",
      "base_commit_sha",
      "base_digest",
      "git_commit_sha",
      "git_digest",
      "draft_digest",
      "plan_fingerprint",
      "created_at",
    ]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    // Settling conflicts is exactly what an update is for.
    for (const column of ["status", "unresolved_count", "guard"]) {
      expect(guard).not.toContain(`new.${column} is distinct from old.${column}`);
    }
    expect(statements).toMatch(
      new RegExp(
        `create trigger trg_draft_sync_plans_guard_identity\\s+before update on ${PLANS}\\s+for each row\\s+execute function apiome\\.draft_sync_plans_guard_identity\\(\\)`,
      ),
    );
  });

  it("refuses to re-open a settled conflict or to restate what the merge found", () => {
    const guard = functionBody("draft_sync_plans_guard_identity");
    expect(guard).toContain("new.conflict_count is distinct from old.conflict_count");
    expect(guard).toContain("new.conflicts_truncated is distinct from old.conflicts_truncated");
    expect(guard).toContain("if new.unresolved_count > old.unresolved_count then");
  });

  // -- Rule 3 ---------------------------------------------------------------------------------

  it("records the base, Git and draft digests with the commits they belong to", () => {
    const block = tableBlock(PLANS);
    for (const column of ["base_digest", "git_digest", "draft_digest"]) {
      expect(block).toContain(`${column} varchar(128) not null`);
      expect(block).toContain(`check (length(btrim(${column})) > 0)`);
    }
    // A draft has no commit; the two repository sides always do.
    expect(block).toContain("base_commit_sha varchar(64) not null");
    expect(block).toContain("git_commit_sha varchar(64) not null");
    expect(block).not.toContain("draft_commit_sha");
  });

  it("counts what merged and what did not, and keeps the three answers consistent", () => {
    const block = tableBlock(PLANS);
    for (const column of [
      "auto_applied_count",
      "local_count",
      "agreed_count",
      "conflict_count",
      "unresolved_count",
    ]) {
      expect(block).toContain(`${column} integer not null default 0`);
    }
    expect(block).toContain("check (unresolved_count >= 0 and unresolved_count <= conflict_count)");
    // A merge that found more collisions than it stores says so, rather than reading as a merge
    // that found exactly a full page of them.
    expect(block).toContain("conflicts_truncated boolean not null default false");
    expect(block).toContain(`check (status in (${PLAN_STATUSES.map((s) => `'${s}'`).join(", ")}))`);
    // A clean merge changed nothing; a conflicted one has something outstanding; a resolved one
    // had conflicts and has none left.
    expect(block).toContain("status <> 'clean' or auto_applied_count = 0");
    expect(block).toContain(
      "(status in ('clean', 'mergeable') and conflict_count = 0 and unresolved_count = 0)",
    );
    expect(block).toContain("(status = 'conflicted' and conflict_count > 0 and unresolved_count > 0)");
    expect(block).toContain("(status = 'resolved' and conflict_count > 0 and unresolved_count = 0)");
  });

  it("keeps the applied changes as a JSON array", () => {
    const block = tableBlock(PLANS);
    expect(block).toContain("changes jsonb not null default '[]'::jsonb");
    expect(block).toContain("check (jsonb_typeof(changes) = 'array')");
  });

  // -- Rule 4 ---------------------------------------------------------------------------------

  it("locates a conflict in the document and in the repository file", () => {
    const block = tableBlock(CONFLICTS);
    // The root pointer is the empty string, so `pointer` is deliberately not length-checked.
    expect(block).toContain("pointer text not null");
    expect(block).not.toContain("check (length(btrim(pointer)) > 0)");
    expect(block).toContain(`check (scope in (${CONFLICT_SCOPES.map((s) => `'${s}'`).join(", ")}))`);
    expect(block).toContain("group_key varchar(255) not null default ''");
    expect(block).toContain("source_file text not null default ''");
    expect(block).toContain("source_line integer");
    expect(block).toContain("check (source_line is null or source_line > 0)");
    expect(block).toContain("source_url text not null default ''");
  });

  it("carries all three sides of a conflict and what each side did", () => {
    const block = tableBlock(CONFLICTS);
    for (const column of ["base_value", "git_value", "draft_value"]) {
      expect(block).toContain(`${column} jsonb`);
      // JSON null, false and an empty container are legal values, so a missing side is expressed
      // by the kind and never by NOT NULL.
      expect(block).not.toContain(`${column} jsonb not null`);
    }
    for (const column of ["git_kind", "draft_kind"]) {
      expect(block).toContain(`${column} varchar(16) not null`);
      expect(block).toContain(
        `check (${column} in (${CHANGE_KINDS.map((k) => `'${k}'`).join(", ")}))`,
      );
    }
  });

  it("describes one collision once per plan", () => {
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_draft_sync_conflicts_pointer\\s+on ${CONFLICTS} \\(plan_id, pointer\\)`,
      ),
    );
    expect(tableBlock(CONFLICTS)).toContain(
      "plan_id uuid not null references draft_sync_plans(id) on delete cascade",
    );
  });

  // -- Rule 5 ---------------------------------------------------------------------------------

  it("settles a conflict towards exactly one of the two sides", () => {
    const block = tableBlock(CONFLICTS);
    expect(block).toContain(
      `check (resolution is null or resolution in (${RESOLUTIONS.map((r) => `'${r}'`).join(", ")}))`,
    );
    // There is no third option, because a merge result is not an editor.
    expect(block).not.toContain("'custom'");
    expect(block).toContain("check ((resolution is null) = (resolved_at is null))");
    expect(block).toContain(
      "check (resolved_at is not null or (resolved_by is null and resolution_note is null))",
    );
  });

  it("refuses to re-decide a settled conflict or to restate what it is about", () => {
    const guard = functionBody("draft_sync_conflicts_guard_settlement");
    for (const column of [
      "plan_id",
      "tenant_id",
      "pointer",
      "scope",
      "git_kind",
      "draft_kind",
      "base_value",
      "git_value",
      "draft_value",
      "created_at",
    ]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    expect(guard).toContain(
      "if old.resolution is not null and new.resolution is distinct from old.resolution then",
    );
    expect(statements).toMatch(
      new RegExp(
        `create trigger trg_draft_sync_conflicts_guard_settlement\\s+before update on ${CONFLICTS}\\s+for each row\\s+execute function apiome\\.draft_sync_conflicts_guard_settlement\\(\\)`,
      ),
    );
    // A BEFORE DELETE guard would also fire for the rows a cascade removes, taking the rest of the
    // schema hostage — the V265 lesson.
    expect(statements).not.toContain(`delete on ${CONFLICTS}`);
    expect(statements).not.toContain(`delete on ${PLANS}`);
  });

  // -- Shape ----------------------------------------------------------------------------------

  it("gives a credential nowhere to sit on either table", () => {
    for (const table of [PLANS, CONFLICTS]) {
      const block = tableBlock(table);
      for (const word of CREDENTIAL_WORDS) {
        expect(block, `${table} must not name a column ${word}`).not.toContain(word);
      }
    }
  });

  it("indexes the reads the panel and the tenant sweep make", () => {
    for (const [index, table, columns] of [
      ["idx_draft_sync_plans_version_created", PLANS, "\\(version_id, created_at desc\\)"],
      ["idx_draft_sync_plans_binding_created", PLANS, "\\(binding_id, created_at desc\\)"],
      ["idx_draft_sync_conflicts_plan_created", CONFLICTS, "\\(plan_id, created_at\\)"],
    ]) {
      expect(statements).toMatch(
        new RegExp(`create index if not exists ${index}\\s+on ${table} ${columns}`),
      );
    }
    expect(statements).toContain("where status = 'conflicted'");
    expect(statements).toContain("where resolution is null");
    expect(statements).not.toContain("create type");
  });

  it("documents both tables and every column whose meaning is not obvious", () => {
    for (const table of [PLANS, CONFLICTS]) {
      expect(statements).toContain(`comment on table ${table} is`);
    }
    for (const column of [
      "base_digest",
      "git_digest",
      "draft_digest",
      "plan_fingerprint",
      "status",
      "changes",
      "conflicts_truncated",
      "guard",
      "candidate_id",
    ]) {
      expect(statements).toContain(`comment on column ${PLANS}.${column} is`);
    }
    for (const column of ["pointer", "scope", "git_kind", "draft_kind", "source_line", "resolution"]) {
      expect(statements).toContain(`comment on column ${CONFLICTS}.${column} is`);
    }
  });

  it("carries rollback notes for a shared environment", () => {
    expect(lower).toContain(`drop table if exists apiome.${CONFLICTS}`);
    expect(lower).toContain(`drop table if exists apiome.${PLANS}`);
    expect(lower).toContain("drop function if exists apiome.draft_sync_plans_guard_identity");
    expect(lower).toContain("drop function if exists apiome.draft_sync_conflicts_guard_settlement");
  });
});
