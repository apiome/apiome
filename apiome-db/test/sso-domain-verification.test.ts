/**
 * Structural assertions over the SSO domain-verification migration (EID-1.2, #5012).
 *
 * V393 moves domain uniqueness from "typed in" to "proved": a provider lists a domain once, an
 * unverified domain reserves nothing, and a verified one is unique installation-wide. DB-free
 * contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V393__sso_domain_verification_5012.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("SSO domain verification migration (EID-1.2)", () => {
  it("is present in scripts/ and ordered after V392", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V392__required_publish_level_gvm_1_3.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("drops the installation-wide unique on every domain row", () => {
    expect(lower).toMatch(/drop constraint if exists sso_provider_domain_domain_key;/);
  });

  it("lets a provider list a domain only once", () => {
    expect(lower).toMatch(
      /add constraint sso_provider_domain_provider_domain_key unique \(provider_id, domain\);/,
    );
  });

  it("keeps a verified domain unique across the installation", () => {
    expect(lower).toMatch(
      /create unique index if not exists sso_provider_domain_verified_uq\s+on apiome\.sso_provider_domain \(domain\)\s+where verified_at is not null;/,
    );
  });

  it("is idempotent", () => {
    expect(lower).toMatch(/if not exists \(\s*select 1 from pg_constraint/);
    expect(lower).toMatch(/create index if not exists sso_provider_domain_domain_idx/);
  });
});
