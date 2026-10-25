/**
 * Structural assertions over V319: deleting an account releases its email address and sign-in
 * identities, so the person can sign up again. DB-free contract tests; apiome-ui's `deleteUser`
 * (`apiome-ui/lib/db/admin-helper.ts`) does the same for each new deletion.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V319__release_deleted_user_identities.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n")
    .replace(/\s+/g, " ");
});

describe("release deleted user identities (V319)", () => {
  it("is present in scripts/ and ordered after V318", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V318__email_verification_pending_password.sql"),
    );
  });

  it("keeps the old address in deleted_email and gives deleted rows a placeholder", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain("add column if not exists deleted_email varchar(255)");
    expect(statements).toContain("set deleted_email = coalesce(deleted_email, email)");
    expect(statements).toContain("email = 'deleted+' || id::text || '@deleted.invalid'");
    // Only deleted rows, and a re-run leaves already released rows alone.
    expect(statements).toMatch(
      /where deleted_at is not null and email <> 'deleted\+' \|\| id::text \|\| '@deleted\.invalid'/,
    );
  });

  it("removes what could still sign in, or block a new sign-up, for deleted accounts only", () => {
    for (const [table, column] of [
      ["session", '"userid"'],
      ["account", '"userid"'],
      ["external_auth_providers", "user_id"],
      ["email_verification_token", "user_id"],
    ]) {
      expect(statements).toContain(
        `delete from apiome.${table} where ${column} in (select id from apiome.users where deleted_at is not null)`,
      );
    }
  });
});
