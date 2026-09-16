/**
 * Structural assertions over the branch-to-draft binding migration (#4737, GNC-2.1).
 *
 * V264 adds `apiome.draft_repository_bindings` — one draft version pinned to one repository
 * provider, ref and source path, with the digest of the source it is synchronized with — and
 * `apiome.draft_binding_sync_candidates`, where an observed movement of a bound ref lands instead
 * of rewriting the draft. The provider webhook/status adapter (GNC-2.2) raises candidates; the
 * three-way synchronization (GNC-2.3) resolves them.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's
 * acceptance criteria turn into schema rather than habit:
 *
 *   1. **At most one active binding per draft** — a partial unique index on `version_id`.
 *   2. **Binding history is retained** — releasing stamps a row, it is never deleted, and a
 *      released row is frozen.
 *   3. **The source digest is stored, and only it moves** — a trigger freezes what a binding names.
 *   4. **A ref update becomes a candidate** — twice idempotent (target commit, provider delivery).
 *   5. **A resolved candidate is frozen** — `pending` settles once.
 *   6. **Scope cascades from tenant, project and version; the binder and the registration survive.**
 *
 * There is deliberately **no RBAC change**: binding needs `versions:edit` plus a proven repository
 * read, which apiome-rest performs. These must stay in lock-step with apiome-rest's
 * `app.draft_bindings` vocabulary and its `tests/test_draft_binding_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V264__draft_repository_bindings_gnc_2_1.sql";
const BINDINGS = "draft_repository_bindings";
const CANDIDATES = "draft_binding_sync_candidates";

/** The three release reasons, in the order the migration lists them. */
const RELEASE_REASONS = ["replaced", "unbound", "repository_removed"];

/** The four candidate states, in the order the migration lists them. */
const CANDIDATE_STATUSES = ["pending", "applied", "dismissed", "superseded"];

/** The three ways a candidate can be raised. */
const CANDIDATE_ORIGINS = ["webhook", "manual", "sweep"];

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

describe("draft repository bindings migration", () => {
  it("is present in scripts/ and ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V263__notifications_col_3_1.sql"));
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(statements).toMatch(new RegExp(`create table if not exists ${BINDINGS} \\(`));
    expect(statements).toMatch(new RegExp(`create table if not exists ${CANDIDATES} \\(`));
  });

  it("allows one active binding per draft version and any number of released ones", () => {
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_draft_repository_bindings_active_version\\s+on ${BINDINGS} \\(version_id\\) where released_at is null`,
      ),
    );
  });

  it("names the provider coordinates a webhook delivery is matched against", () => {
    const block = tableBlock(BINDINGS);
    expect(block).toContain("provider varchar(32) not null");
    for (const provider of ["github", "gitlab", "bitbucket"]) {
      expect(block).toContain(`'${provider}'`);
    }
    expect(block).toContain("repo_full_name varchar(512) not null");
    expect(block).toContain("ref varchar(255) not null");
    expect(block).toContain("path text not null default ''");
    expect(statements).not.toContain("create type");
  });

  it("indexes the webhook lookup on the active bindings of a repository's ref", () => {
    expect(statements).toMatch(
      new RegExp(
        `create index if not exists idx_draft_repository_bindings_repo_ref_active\\s+on ${BINDINGS} \\(repository_id, ref\\) where released_at is null`,
      ),
    );
  });

  it("stores the source digest and the commit it was taken at, both required", () => {
    const block = tableBlock(BINDINGS);
    expect(block).toContain("commit_sha varchar(64) not null");
    expect(block).toContain("source_digest varchar(128) not null");
    expect(block).toContain("synchronized_at timestamp with time zone not null");
  });

  it("retains history by releasing rather than deleting, with a named reason", () => {
    const block = tableBlock(BINDINGS);
    expect(block).toContain("released_at timestamp with time zone");
    expect(block).toContain("released_by uuid references users(id) on delete set null");
    for (const reason of RELEASE_REASONS) {
      expect(block).toContain(`'${reason}'`);
    }
    // An active binding carries no releaser and no reason.
    expect(block).toContain(
      "check (released_at is not null or (released_by is null and release_reason is null))",
    );
    expect(statements).not.toMatch(new RegExp(`delete from apiome\\.${BINDINGS}`));
  });

  it("freezes what a binding names, and freezes a released binding entirely", () => {
    const guard = functionBody("draft_repository_bindings_guard_identity");
    for (const column of [
      "tenant_id",
      "project_id",
      "version_id",
      "provider",
      "repo_full_name",
      "repo_url",
      "ref",
      "path",
      "created_at",
    ]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    // The synchronized pair moves while active — it is not in the identity list.
    expect(guard).toContain("if old.released_at is not null");
    expect(guard).toContain("new.commit_sha is distinct from old.commit_sha");
    expect(guard).toContain("new.source_digest is distinct from old.source_digest");
    expect(statements).toMatch(
      new RegExp(
        `create trigger trg_draft_repository_bindings_guard_identity\\s+before update on ${BINDINGS}\\s+for each row\\s+execute function apiome\\.draft_repository_bindings_guard_identity\\(\\)`,
      ),
    );
  });

  it("cascades from tenant, project and version but survives its binder and its registration", () => {
    const block = tableBlock(BINDINGS);
    expect(block).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(block).toContain("project_id uuid not null references projects(id) on delete cascade");
    expect(block).toContain("version_id uuid not null references versions(id) on delete cascade");
    expect(block).toContain("created_by uuid references users(id) on delete set null");
    expect(block).toContain("repository_id uuid references tenant_repositories(id) on delete set null");
    // ON DELETE SET NULL has to be able to clear the registration on a frozen row too.
    expect(functionBody("draft_repository_bindings_guard_identity")).toContain(
      "(new.repository_id is distinct from old.repository_id and new.repository_id is not null)",
    );
  });
});

describe("draft binding sync candidates migration", () => {
  it("records where the ref moved from and to, and leaves the new digest unread", () => {
    const block = tableBlock(CANDIDATES);
    expect(block).toContain("from_commit_sha varchar(64) not null");
    expect(block).toContain("from_digest varchar(128) not null");
    expect(block).toContain("to_commit_sha varchar(64) not null");
    // A delivery names a commit, not a document, so the target digest starts unknown.
    expect(block).toMatch(/to_digest varchar\(128\)(?!\s+not null)/);
  });

  it("stores only the four statuses and three origins, as checks and not enums", () => {
    const block = tableBlock(CANDIDATES);
    for (const status of CANDIDATE_STATUSES) {
      expect(block).toContain(`'${status}'`);
    }
    for (const origin of CANDIDATE_ORIGINS) {
      expect(block).toContain(`'${origin}'`);
    }
    expect(block).toContain("status varchar(16) not null default 'pending'");
    expect(statements).not.toContain("create type");
  });

  it("is idempotent per target commit and per provider delivery", () => {
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_draft_binding_sync_candidates_pending\\s+on ${CANDIDATES} \\(binding_id, to_commit_sha\\) where status = 'pending'`,
      ),
    );
    expect(statements).toMatch(
      new RegExp(
        `create unique index if not exists uq_draft_binding_sync_candidates_delivery\\s+on ${CANDIDATES} \\(binding_id, delivery_id\\) where delivery_id is not null`,
      ),
    );
  });

  it("ties pending exactly to an unresolved row", () => {
    const block = tableBlock(CANDIDATES);
    expect(block).toContain("check ((status = 'pending') = (resolved_at is null))");
    expect(block).toContain(
      "check (resolved_at is not null or (resolved_by is null and resolution_note is null))",
    );
  });

  it("lets a candidate settle once and never move again", () => {
    const guard = functionBody("draft_binding_sync_candidates_guard_resolved");
    for (const column of [
      "binding_id",
      "tenant_id",
      "ref",
      "from_commit_sha",
      "from_digest",
      "to_commit_sha",
      "origin",
      "delivery_id",
      "detected_at",
    ]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    expect(guard).toContain("if old.status <> 'pending'");
    expect(guard).toContain("new.status is distinct from old.status");
    expect(statements).toMatch(
      new RegExp(
        `create trigger trg_draft_binding_sync_candidates_guard_resolved\\s+before update on ${CANDIDATES}\\s+for each row\\s+execute function apiome\\.draft_binding_sync_candidates_guard_resolved\\(\\)`,
      ),
    );
  });

  it("indexes a binding's candidates newest first and a tenant's outstanding ones", () => {
    expect(statements).toMatch(
      new RegExp(
        `create index if not exists idx_draft_binding_sync_candidates_binding_detected\\s+on ${CANDIDATES} \\(binding_id, detected_at desc\\)`,
      ),
    );
    expect(statements).toMatch(
      new RegExp(
        `create index if not exists idx_draft_binding_sync_candidates_tenant_pending\\s+on ${CANDIDATES} \\(tenant_id, detected_at desc\\) where status = 'pending'`,
      ),
    );
  });

  it("cascades from its binding and its tenant", () => {
    const block = tableBlock(CANDIDATES);
    expect(block).toContain(
      `binding_id uuid not null references ${BINDINGS}(id) on delete cascade`,
    );
    expect(block).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
  });

  it("changes no RBAC", () => {
    expect(statements).not.toContain("seed_builtin_roles");
    expect(statements).not.toContain("role_permissions");
  });
});
