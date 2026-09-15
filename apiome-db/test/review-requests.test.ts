/**
 * Structural assertions over the review requests migration (#4517, COL-2.1).
 *
 * V261 adds `apiome.reviews` and `apiome.review_reviewers` — the record of who was asked to review
 * a draft version, what each reviewer decided, and on which content. The review page (COL-2.2),
 * the approval publish gate (COL-2.3), and review status surfaces (COL-2.4) all read it.
 *
 * DB-free contract tests pin the migration shape, concentrating on the rules the ticket's scope
 * turns into schema rather than habit:
 *
 *   1. **`draft` is not stored** — a review row is `in_review | approved | changes_requested`.
 *   2. **One open review per version** — a partial unique index on `version_id`.
 *   3. **Rounds** — `reviews.round` + `spec_fingerprint`, reviewer rows unique per round.
 *   4. **Decisions are immutable history** — a trigger refuses changing a recorded decision and
 *      deciding outside the current round of an open review that is in review.
 *   5. **A withdrawn review is frozen** — a trigger on `reviews`.
 *   6. **Scope cascades from tenant/project/version; deleting a user keeps their decisions.**
 *
 * There is deliberately **no RBAC change**: the permissions and the reviewer assignment are
 * enforced in apiome-rest. These must stay in lock-step with apiome-rest's `app.review_lifecycle`
 * vocabulary and its `tests/test_review_requests_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V261__review_requests_4517.sql";
const REVIEWS = "reviews";
const REVIEWERS = "review_reviewers";

let lower = "";
/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** One table's column block: from its CREATE TABLE to the closing `);`. */
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

describe("review requests migration", () => {
  it("is present in scripts/ and ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V260__comment_anchor_resilience_4516.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    for (const table of [REVIEWS, REVIEWERS]) {
      expect(statements).toMatch(new RegExp(`create table if not exists ${table} \\(`));
    }
  });

  it("stores only the three review states, never draft", () => {
    const reviews = tableBlock(REVIEWS);
    expect(reviews).toContain("state varchar(24) not null default 'in_review'");
    expect(reviews).toContain("check (state in ('in_review', 'approved', 'changes_requested'))");
    expect(statements).not.toContain("'draft'");
  });

  it("allows one open review per version", () => {
    expect(statements).toMatch(
      /create unique index if not exists uq_reviews_open_version\s+on reviews \(version_id\) where closed_at is null/,
    );
  });

  it("records rounds and the content each round judges", () => {
    const reviews = tableBlock(REVIEWS);
    expect(reviews).toContain("round integer not null default 1");
    expect(reviews).toContain("spec_fingerprint varchar(128) not null");
    const reviewers = tableBlock(REVIEWERS);
    expect(reviewers).toContain("round integer not null");
    expect(reviewers).toContain("unique (review_id, round, user_id)");
  });

  it("records a decision with its time, and a pending row with neither time nor note", () => {
    const reviewers = tableBlock(REVIEWERS);
    expect(reviewers).toContain("check (decision in ('approve', 'request_changes', 'pending'))");
    expect(reviewers).toContain("check ((decision = 'pending') = (decided_at is null))");
    expect(reviewers).toContain("check (decision <> 'pending' or note is null)");
    expect(reviewers).toContain("check (note is null or length(note) <= 5000)");
  });

  it("keeps recorded decisions immutable with a trigger", () => {
    const guard = functionBody("review_reviewers_guard_decision");
    expect(guard).toContain("if old.decision <> 'pending' then");
    expect(guard).toContain("new.decision is distinct from old.decision");
    expect(guard).toContain("new.note is distinct from old.note");
    expect(guard).toContain(
      "parent_closed_at is not null or parent_state <> 'in_review' or parent_round <> new.round",
    );
    expect(statements).toMatch(
      /create trigger trg_review_reviewers_guard_decision\s+before update on review_reviewers\s+for each row\s+execute function apiome\.review_reviewers_guard_decision\(\)/,
    );
  });

  it("lets a deleted user's decisions survive without their id", () => {
    expect(tableBlock(REVIEWERS)).toContain("user_id uuid references users(id) on delete set null");
    expect(functionBody("review_reviewers_guard_decision")).toContain(
      "(new.user_id is distinct from old.user_id and new.user_id is not null)",
    );
  });

  it("freezes a withdrawn review with a trigger", () => {
    const guard = functionBody("reviews_guard_closed");
    expect(guard).toContain("if old.closed_at is not null");
    for (const column of ["state", "round", "spec_fingerprint", "closed_at", "version_id"]) {
      expect(guard).toContain(`new.${column} is distinct from old.${column}`);
    }
    expect(statements).toMatch(
      /create trigger trg_reviews_guard_closed\s+before update on reviews\s+for each row\s+execute function apiome\.reviews_guard_closed\(\)/,
    );
  });

  it("cascades from tenant, project, and version and keeps history when users go", () => {
    const reviews = tableBlock(REVIEWS);
    for (const [column, target] of [
      ["tenant_id", "tenants"],
      ["project_id", "projects"],
      ["version_id", "versions"],
    ]) {
      expect(reviews).toContain(`${column} uuid not null references ${target}(id) on delete cascade`);
    }
    expect(reviews).toContain("requested_by uuid references users(id) on delete set null");
    expect(reviews).toContain("closed_by uuid references users(id) on delete set null");
    expect(tableBlock(REVIEWERS)).toContain(
      "review_id uuid not null references reviews(id) on delete cascade",
    );
  });

  it("changes no RBAC and creates no enum type", () => {
    expect(statements).not.toContain("seed_builtin_roles");
    expect(statements).not.toContain("role_permissions");
    expect(statements).not.toContain("create type");
  });
});
