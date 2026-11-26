/**
 * Structural assertions over the webhook delivery-log migration (#6950, PFX-5.6).
 *
 * V445 orders a webhook's firings and indexes the workspace's, so the **Webhooks** page reads
 * each webhook's latest delivery and both delivery logs without sorting every firing. DB-free
 * contract tests pin it:
 *
 *   1. It sets its own search path first.
 *   2. The history index leads with (webhook_id, tenant_id), so the webhook reference's check is
 *      still served once the older index is dropped.
 *   3. The workspace index leads with tenant_id and orders newest first.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V445__pact_webhook_delivery_log_6950.sql";

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("webhook delivery-log migration (PFX-5.6)", () => {
  it("is present in scripts/ and ordered after the webhooks migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V436__pact_webhooks_6922.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("builds the ordered history index before dropping the one it replaces", () => {
    const history = ddl.indexOf(
      "create index if not exists idx_pact_triggered_webhook_history on pact_triggered_webhook (webhook_id, tenant_id, created_at desc, id desc)",
    );
    const dropped = ddl.indexOf("drop index if exists idx_pact_triggered_webhook_webhook");
    expect(history).toBeGreaterThan(0);
    expect(dropped).toBeGreaterThan(history);
  });

  it("indexes the workspace's firings newest first", () => {
    expect(ddl).toContain(
      "create index if not exists idx_pact_triggered_webhook_recent on pact_triggered_webhook (tenant_id, created_at desc, id desc)",
    );
  });

  it("changes no column or rule of the table", () => {
    expect(ddl).not.toContain("alter table");
    expect(ddl).not.toContain("constraint");
  });
});
