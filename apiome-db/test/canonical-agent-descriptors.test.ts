/**
 * Structural assertions over the agent-descriptor persistence migration (#3977, MFI-18.4).
 *
 * V306 adds `api_agent_descriptors` / `api_agent_skills` beside V135's canonical tree and widens
 * `api_artifacts_paradigm_check` to the `agent` paradigm, which V135 predated. These DB-free tests
 * pin the shape the REST persistence codec (`apiome-rest/src/app/canonical_persistence.py`)
 * writes; the lossless round trip itself is `apiome-rest/tests/test_agent_descriptor_paradigm.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V306__canonical_agent_descriptors_3977.sql";

/** Columns the persistence codec inserts, per table. */
const COLUMNS: Record<string, string[]> = {
  api_agent_descriptors: [
    "tenant_id", "version_id", "artifact_id", "key", "name", "description", "agent_version",
    "url", "protocol", "protocol_version", "provider", "capabilities", "default_input_modes",
    "default_output_modes", "security_schemes", "security", "service_ref", "ordinal", "extras",
  ],
  api_agent_skills: [
    "tenant_id", "version_id", "artifact_id", "agent_id", "key", "skill_id", "name",
    "description", "tags", "examples", "input_modes", "output_modes", "security",
    "operation_ref", "ordinal", "extras",
  ],
};

/** The body of `CREATE TABLE … (…);` for ``table``. */
function tableBody(sql: string, table: string): string {
  const match = sql.match(new RegExp(`CREATE TABLE IF NOT EXISTS ${table} \\(([\\s\\S]*?)\\n\\);`));
  return match ? match[1] : "";
}

describe(`${MIGRATION} — agent descriptors and skills`, () => {
  let sql = "";

  beforeAll(async () => {
    sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  });

  it("is registered in the migration sequence", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const names = files.map((f) => (typeof f === "string" ? f : f.name ?? f.file ?? ""));
    expect(names.some((name) => String(name).endsWith(MIGRATION))).toBe(true);
  });

  it.each(Object.entries(COLUMNS))("creates %s with every column the codec writes", (table, cols) => {
    const body = tableBody(sql, table);
    expect(body).not.toBe("");
    for (const col of cols) expect(body).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
  });

  it("cascades skills from their agent and agents from their artifact", () => {
    expect(tableBody(sql, "api_agent_descriptors")).toMatch(/artifact_id UUID NOT NULL REFERENCES api_artifacts\(id\) ON DELETE CASCADE/);
    expect(tableBody(sql, "api_agent_skills")).toMatch(/agent_id UUID NOT NULL REFERENCES api_agent_descriptors\(id\) ON DELETE CASCADE/);
  });

  it("keeps keys unique among live rows so skill diffs line up by id", () => {
    expect(sql).toMatch(/uq_api_agent_descriptors_artifact_key\s+ON api_agent_descriptors\(artifact_id, key\) WHERE deleted_at IS NULL/);
    expect(sql).toMatch(/uq_api_agent_skills_agent_key\s+ON api_agent_skills\(agent_id, key\) WHERE deleted_at IS NULL/);
  });

  it("admits the agent paradigm on api_artifacts", () => {
    expect(sql).toMatch(/DROP CONSTRAINT IF EXISTS api_artifacts_paradigm_check/);
    expect(sql).toMatch(/CHECK \(paradigm IN \('rest', 'rpc', 'event', 'graph', 'data_schema', 'agent'\)\)/);
  });
});
