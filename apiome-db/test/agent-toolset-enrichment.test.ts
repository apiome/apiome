/**
 * Structural assertions over the agent toolset enrichment migration (#4531, AGX-1.3).
 *
 * V273 stores copilot-proposed tool and parameter descriptions for review, and the per-toolset
 * opt-out. DB-free contract tests pin its rules:
 *
 *   1. **Nothing is served without acceptance**: only a reviewed, `accepted` row carries
 *      `accepted_description` (`agent_toolset_enrichments_review_ck`).
 *   2. **One proposal per description per toolset** (`UNIQUE (toolset_id, target_key)`), which
 *      makes the pass idempotent.
 *   3. **Opting out serves raw descriptions**: `agent_toolsets.description_enrichment`, default true.
 *   4. **Proposals go with their toolset** (`ON DELETE CASCADE`).
 *
 * These must stay in lock-step with apiome-rest's `app.agent_toolset_enrichment` and the
 * `db.*agent_toolset_enrichment*` accessors.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V273__agent_toolset_enrichment_agx_1_3.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

describe("agent toolset enrichment migration (AGX-1.3)", () => {
  it("is present in scripts/ and ordered after the agent key quotas migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V272__agent_key_quotas_agx_3_2.sql"));
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("adds the opt-out, serving accepted text by default", () => {
    expect(ddl).toContain(
      "alter table agent_toolsets add column if not exists description_enrichment boolean not null default true",
    );
  });

  it("cascades proposals with their toolset", () => {
    expect(ddl).toContain(
      "toolset_id uuid not null references agent_toolsets(id) on delete cascade",
    );
  });

  it("makes accepted text impossible without a review", () => {
    expect(ddl).toContain(
      "(status = 'proposed' and accepted_description is null and reviewed_at is null) " +
        "or (status = 'accepted' and accepted_description is not null and reviewed_at is not null) " +
        "or (status = 'rejected' and accepted_description is null and reviewed_at is not null)",
    );
    expect(ddl).toContain("check (status in ('proposed', 'accepted', 'rejected'))");
  });

  it("keys a parameter name to parameter targets only", () => {
    expect(ddl).toContain("check (target_kind in ('tool', 'parameter'))");
    expect(ddl).toContain("(target_kind = 'tool') = (parameter_name is null)");
  });

  it("keeps one proposal per description per toolset", () => {
    expect(ddl).toContain("constraint agent_toolset_enrichments_target_uq unique (toolset_id, target_key)");
  });

  it("indexes the accepted proposals a compile reads", () => {
    expect(ddl).toMatch(
      /create index if not exists idx_agent_toolset_enrichments_accepted on agent_toolset_enrichments \(toolset_id\) where status = 'accepted'/,
    );
  });

  it("documents its rollback", () => {
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.agent_toolset_enrichments;");
    expect(sql).toContain("ALTER TABLE apiome.agent_toolsets DROP COLUMN IF EXISTS description_enrichment;");
  });
});
