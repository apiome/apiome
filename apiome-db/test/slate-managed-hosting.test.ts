/**
 * Structural assertions over the managed Slate hosting migration (APX-3.1, private-suite#2456).
 *
 * V186 adds the deployment control plane: content-addressed signed artifacts, environments,
 * immutable releases, the activation ledger, retention, domains and an append-only audit.
 *
 * The suite is DB-free — this package asserts migration SQL structurally, and application
 * against a live database is proven in apiome-rest — so these tests pin the migration's
 * contract. They are deliberately weighted toward the four acceptance criteria, because those
 * are the claims the schema is what makes true:
 *
 *   1. every build carries content/source/config digests and an immutable release id;
 *   2. activation is atomic;
 *   3. promotion never rebuilds and rollback restores a retained artifact;
 *   4. concurrent promotion, failed activation, retention and audit are enforced, not assumed.
 *
 * A guarantee that lives only in the service layer is a guarantee that survives exactly as long
 * as the next caller behaves, so the immutability and append-only rules are asserted here as
 * database triggers rather than as documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V186__slate_managed_hosting_2456.sql";

/** Every table the control plane introduces. */
const TABLES = [
  "slate_sites",
  "slate_artifacts",
  "slate_environments",
  "slate_releases",
  "slate_release_regions",
  "slate_release_approvals",
  "slate_release_checks",
  "slate_release_phases",
  "slate_release_logs",
  "slate_release_changed_pages",
  "slate_release_audit",
  "slate_domains",
  "slate_activations",
] as const;

/** Tables that carry a denormalized tenant_id, per the repo's tenancy convention. */
const TENANT_SCOPED = [
  "slate_sites",
  "slate_artifacts",
  "slate_environments",
  "slate_releases",
  "slate_release_audit",
  "slate_domains",
  "slate_activations",
] as const;

let sql = "";
let lower = "";

/** Extract a single `CREATE TABLE ... (...);` body so column assertions cannot match a neighbour. */
function tableBody(table: string): string {
  const start = sql.indexOf(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
  if (start === -1) throw new Error(`table ${table} not found in ${MIGRATION}`);
  const end = sql.indexOf("\n);", start);
  if (end === -1) throw new Error(`unterminated CREATE TABLE for ${table}`);
  return sql.slice(start, end);
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("managed Slate hosting migration", () => {
  it("is present in scripts/ and ordered after V185", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V185__source_change_audit_2360.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates every control-plane table idempotently", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
    }
  });

  it("names the ticket so the schema is traceable to its rationale", () => {
    expect(sql).toContain("APX-3.1");
    expect(sql).toContain("private-suite#2456");
  });

  /* ---------------------------------------------------------------------- */
  /* Tenancy                                                                */
  /* ---------------------------------------------------------------------- */

  it("scopes every top-level table to a tenant", () => {
    for (const table of TENANT_SCOPED) {
      expect(tableBody(table)).toMatch(
        /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\)/,
      );
    }
  });

  it("cascades tenant deletion rather than orphaning release history", () => {
    for (const table of TENANT_SCOPED) {
      expect(tableBody(table)).toMatch(
        /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
      );
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 1 — digests and immutable release id                         */
  /* ---------------------------------------------------------------------- */

  it("requires all three digests on every artifact", () => {
    const body = tableBody("slate_artifacts");
    for (const column of ["content_digest", "source_digest", "config_digest"]) {
      expect(body).toMatch(new RegExp(`${column}\\s+TEXT NOT NULL`));
    }
  });

  it("constrains digests to the sha256 form rather than accepting any string", () => {
    const body = tableBody("slate_artifacts");
    for (const column of ["content_digest", "source_digest", "config_digest"]) {
      expect(body).toMatch(new RegExp(`${column}[^,]*\\^sha256:\\[0-9a-f\\]\\{64\\}\\$`));
    }
  });

  it("content-addresses artifacts so identical bytes are one identity per site", () => {
    expect(tableBody("slate_artifacts")).toContain("UNIQUE (site_id, content_digest)");
  });

  it("requires a signature and its key id on every artifact", () => {
    const body = tableBody("slate_artifacts");
    expect(body).toMatch(/signature\s+TEXT NOT NULL/);
    expect(body).toMatch(/signature_key_id\s+TEXT NOT NULL/);
  });

  it("carries a build manifest/SBOM", () => {
    expect(tableBody("slate_artifacts")).toMatch(/manifest\s+JSONB NOT NULL/);
  });

  it("gives every release a human-quotable id unique within its site", () => {
    const body = tableBody("slate_releases");
    expect(body).toMatch(/release_ref\s+TEXT NOT NULL/);
    expect(body).toContain("UNIQUE (site_id, release_ref)");
  });

  it("records the full source and actor identity on the release itself", () => {
    const body = tableBody("slate_releases");
    for (const column of [
      "source_commit",
      "source_ref",
      "source_message",
      "actor_name",
      "actor_kind",
    ]) {
      expect(body).toMatch(new RegExp(`${column}\\s+TEXT NOT NULL`));
    }
  });

  it("stores the actor name rather than only a user reference, so history survives deletion", () => {
    // actor_id may be nulled by user deletion; actor_name may not, or the timeline forgets who acted.
    expect(tableBody("slate_releases")).toMatch(
      /actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/,
    );
    expect(tableBody("slate_releases")).toMatch(/actor_name\s+TEXT NOT NULL/);
  });

  it("uses the Release Center status vocabulary verbatim", () => {
    const body = tableBody("slate_releases");
    for (const status of [
      "queued",
      "building",
      "ready",
      "review",
      "active",
      "superseded",
      "failed",
      "rolled-back",
    ]) {
      expect(body).toContain(`'${status}'`);
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 1/4 — immutability is enforced by the database               */
  /* ---------------------------------------------------------------------- */

  it("installs an immutability trigger on releases", () => {
    expect(sql).toContain("CREATE OR REPLACE FUNCTION apiome.slate_release_immutability_guard()");
    expect(sql).toContain("CREATE TRIGGER trg_slate_release_immutability");
    expect(lower).toMatch(/before update on apiome\.slate_releases/);
  });

  it("guards every field release-model.ts declares immutable", () => {
    // Mirrors IMMUTABLE_FIELDS in designer/lib/authoring/release-model.ts.
    for (const column of [
      "id",
      "tenant_id",
      "site_id",
      "environment_id",
      "release_ref",
      "source_commit",
      "source_ref",
      "source_message",
      "actor_id",
      "actor_name",
      "actor_kind",
      "impact",
      "created_at",
    ]) {
      expect(sql).toMatch(new RegExp(`NEW\\.${column}\\s+IS DISTINCT FROM OLD\\.${column}`));
    }
  });

  it("permits attaching an artifact once but never repointing it", () => {
    // A release whose bytes can be swapped would let approved, audited history serve something else.
    expect(sql).toMatch(
      /OLD\.artifact_id IS NOT NULL AND NEW\.artifact_id IS DISTINCT FROM OLD\.artifact_id/,
    );
  });

  it("raises rather than silently ignoring an immutable-field update", () => {
    expect(sql).toMatch(/RAISE EXCEPTION\s*\n?\s*'slate_releases is immutable/);
  });

  it("makes the audit log append-only at the database, both verbs", () => {
    expect(sql).toContain("CREATE OR REPLACE FUNCTION apiome.slate_release_audit_append_only()");
    expect(sql).toContain("CREATE TRIGGER trg_slate_release_audit_append_only");
    expect(lower).toMatch(/before update or delete on apiome\.slate_release_audit/);
    expect(sql).toMatch(/RAISE EXCEPTION\s*\n?\s*'slate_release_audit is append-only/);
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 2 — atomic activation                                        */
  /* ---------------------------------------------------------------------- */

  it("puts the routing pointer on the environment, so activation is a single-row update", () => {
    const body = tableBody("slate_environments");
    expect(body).toMatch(/active_release_id\s+UUID/);
    // Nullable: a lane that has never served a release is a real, distinct state.
    expect(body).not.toMatch(/active_release_id\s+UUID NOT NULL/);
  });

  it("carries an optimistic-concurrency token for activation", () => {
    expect(tableBody("slate_environments")).toMatch(
      /routing_version\s+BIGINT NOT NULL DEFAULT 0/,
    );
  });

  it("documents the single-statement atomic activation in the migration header", () => {
    expect(lower).toContain("update apiome.slate_environments");
    expect(lower).toContain("routing_version = routing_version + 1");
    expect(lower).toContain("routing_version = :expected");
  });

  it("adds the circular routing foreign key after both tables exist", () => {
    expect(sql).toContain("fk_slate_environments_active_release");
    expect(sql).toMatch(
      /FOREIGN KEY \(active_release_id\)\s*\n?\s*REFERENCES apiome\.slate_releases\(id\)/,
    );
    // Guarded so re-running the migration on a repaired database does not fail on a duplicate.
    expect(sql).toContain("SELECT 1 FROM pg_constraint WHERE conname = 'fk_slate_environments_active_release'");
  });

  it("models the three lane kinds", () => {
    const body = tableBody("slate_environments");
    expect(body).toContain("kind IN ('production', 'staging', 'preview')");
  });

  it("supports ephemeral preview expiry and robots exclusion", () => {
    const body = tableBody("slate_environments");
    expect(body).toMatch(/expires_at\s+TIMESTAMP WITH TIME ZONE/);
    expect(body).toMatch(/robots_excluded\s+BOOLEAN NOT NULL/);
  });

  it("offers the preview protection modes the roadmap names", () => {
    expect(tableBody("slate_environments")).toContain(
      "access_policy IN ('public', 'tenant', 'password', 'sso')",
    );
  });

  it("separates activation start from activation completion, so the SLO is measurable", () => {
    const body = tableBody("slate_releases");
    expect(body).toMatch(/activated_at\s+TIMESTAMP WITH TIME ZONE/);
    expect(body).toMatch(/activation_completed_at\s+TIMESTAMP WITH TIME ZONE/);
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 3 — promotion never rebuilds, rollback restores              */
  /* ---------------------------------------------------------------------- */

  it("makes the artifact a reference, never a build instruction", () => {
    expect(tableBody("slate_releases")).toMatch(
      /artifact_id\s+UUID REFERENCES apiome\.slate_artifacts\(id\) ON DELETE RESTRICT/,
    );
  });

  it("refuses to delete an artifact a release still points at", () => {
    // ON DELETE RESTRICT rather than CASCADE: retention must not silently strand release history.
    expect(tableBody("slate_releases")).toContain("ON DELETE RESTRICT");
  });

  it("records the routed digest on the activation, so the ledger alone proves no rebuild", () => {
    const body = tableBody("slate_activations");
    expect(body).toMatch(/artifact_digest\s+TEXT NOT NULL/);
    expect(body).toMatch(/\^sha256:\[0-9a-f\]\{64\}\$/);
  });

  it("distinguishes initial activation, promotion and rollback", () => {
    expect(tableBody("slate_activations")).toContain(
      "kind IN ('initial', 'promotion', 'rollback')",
    );
  });

  it("indexes rollback targets: superseded releases that still have an artifact", () => {
    expect(sql).toContain("idx_slate_releases_rollback_targets");
    expect(sql).toMatch(/WHERE status = 'superseded' AND artifact_id IS NOT NULL/);
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 4 — concurrency, failure, retention, audit                   */
  /* ---------------------------------------------------------------------- */

  it("records both concurrency-token values on every activation attempt", () => {
    const body = tableBody("slate_activations");
    expect(body).toMatch(/routing_version_before\s+BIGINT NOT NULL/);
    expect(body).toMatch(/routing_version_after\s+BIGINT/);
  });

  it("has a terminal outcome for a lost concurrent promotion", () => {
    expect(tableBody("slate_activations")).toContain(
      "outcome IN ('pending', 'succeeded', 'partial', 'failed', 'conflict')",
    );
  });

  it("carries an operator-facing failure reason", () => {
    expect(tableBody("slate_activations")).toMatch(/failure_reason\s+TEXT/);
  });

  it("tracks per-region activation, so a partial rollout is not reported as success", () => {
    const body = tableBody("slate_release_regions");
    expect(body).toContain("status IN ('active', 'activating', 'failed')");
    expect(body).toContain("UNIQUE (release_id, region_id)");
    expect(body).toMatch(/reported_at\s+TIMESTAMP WITH TIME ZONE NOT NULL/);
  });

  it("expresses retention as a per-site release count", () => {
    expect(tableBody("slate_sites")).toMatch(
      /retained_releases\s+INTEGER NOT NULL DEFAULT 10 CHECK \(retained_releases >= 1\)/,
    );
  });

  it("marks a reaped artifact rather than deleting it, so history keeps its digest", () => {
    const body = tableBody("slate_artifacts");
    expect(body).toMatch(/reaped_at\s+TIMESTAMP WITH TIME ZONE/);
    expect(body).toMatch(/storage_uri\s+TEXT/);
    // storage_uri must stay nullable: reaping clears the bytes without erasing the row.
    expect(body).not.toMatch(/storage_uri\s+TEXT NOT NULL/);
  });

  it("indexes the retention sweep to artifacts that still hold bytes", () => {
    expect(sql).toContain("idx_slate_artifacts_retained");
    expect(sql).toMatch(/WHERE reaped_at IS NULL/);
  });

  it("binds each approval to the digest it approved", () => {
    const body = tableBody("slate_release_approvals");
    expect(body).toMatch(/digest\s+TEXT NOT NULL/);
    expect(body).toMatch(/\^sha256:\[0-9a-f\]\{64\}\$/);
  });

  it("gives the activation SLO a configured budget to be measured against", () => {
    expect(tableBody("slate_sites")).toMatch(
      /activation_slo_seconds\s+INTEGER NOT NULL DEFAULT 300 CHECK \(activation_slo_seconds > 0\)/,
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Domains                                                                */
  /* ---------------------------------------------------------------------- */

  it("makes a hostname globally unique, not merely unique per tenant", () => {
    // Two tenants claiming one host is a routing ambiguity, not a convenience.
    expect(tableBody("slate_domains")).toContain("UNIQUE (host)");
  });

  it("permits at most one canonical host per lane", () => {
    expect(sql).toContain("uq_slate_domains_primary_per_environment");
    expect(sql).toMatch(/ON apiome\.slate_domains \(environment_id\)\s*\n?\s*WHERE is_primary/);
  });

  it("reports TLS and ownership-verification state separately", () => {
    const body = tableBody("slate_domains");
    expect(body).toContain("tls_status IN ('active', 'provisioning', 'error')");
    expect(body).toContain("verification_status IN ('pending', 'verified', 'failed')");
  });

  it("records certificate issuer and expiry so renewal can be reported before it lapses", () => {
    const body = tableBody("slate_domains");
    expect(body).toMatch(/certificate_issuer\s+TEXT/);
    expect(body).toMatch(/certificate_expires_at\s+TIMESTAMP WITH TIME ZONE/);
  });

  /* ---------------------------------------------------------------------- */
  /* Documentation and indexing conventions                                 */
  /* ---------------------------------------------------------------------- */

  it("documents every table", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`COMMENT ON TABLE apiome.${table} IS`);
    }
  });

  it("documents every column of every table", () => {
    // `id` is exempt: it is the surrogate primary key on every table, its declaration says so,
    // and the repo's existing migrations (V184, V185) do not comment it either. Documenting it
    // thirteen times would add noise without adding a fact.
    for (const table of TABLES) {
      const body = tableBody(table);
      const columns = [...body.matchAll(/^\s{4}([a-z_]+)\s{2,}/gm)]
        .map((m) => m[1])
        .filter((column) => column !== "id");
      expect(columns.length).toBeGreaterThan(0);
      for (const column of columns) {
        expect(
          sql,
          `apiome.${table}.${column} is undocumented`,
        ).toContain(`COMMENT ON COLUMN apiome.${table}.${column} IS`);
      }
    }
  });

  it("documents both trigger functions", () => {
    expect(sql).toContain("COMMENT ON FUNCTION apiome.slate_release_immutability_guard() IS");
    expect(sql).toContain("COMMENT ON FUNCTION apiome.slate_release_audit_append_only() IS");
  });

  it("creates every index idempotently", () => {
    const creates = [...sql.matchAll(/CREATE (?:UNIQUE )?INDEX (IF NOT EXISTS )?/g)];
    expect(creates.length).toBeGreaterThan(0);
    for (const match of creates) {
      expect(match[1], `index created without IF NOT EXISTS: ${match[0]}`).toBeTruthy();
    }
  });

  it("indexes each release child table by its release", () => {
    for (const table of [
      "slate_release_regions",
      "slate_release_approvals",
      "slate_release_checks",
      "slate_release_phases",
      "slate_release_logs",
      "slate_release_changed_pages",
      "slate_release_audit",
    ]) {
      expect(sql).toMatch(new RegExp(`idx_${table}_release`));
    }
  });

  it("is honest in-file about what deploy/ can actually drive today", () => {
    // The repo has a single Caddyfile and no CDN; the schema must not imply a live global edge.
    expect(lower).toContain("caddyfile");
    expect(lower).toContain("control plane");
  });
});
