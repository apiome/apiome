import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

import { listSeedFiles } from "../src/seed.js";

const SEED_DIR = new URL("../seed/dev", import.meta.url).pathname;

describe("listSeedFiles", () => {
  it("returns the dev seed files in load order", async () => {
    const files = await listSeedFiles(SEED_DIR);
    expect(files).toEqual([
      "001_user.sql",
      "002_tenant.sql",
      "003_membership.sql",
      "004_license.sql",
      "005_api_key.sql",
      "006_sample_project.sql",
      "007_multitenant.sql",
    ]);
  });
});

describe("dev seed contents", () => {
  it("inserts the documented sample identifiers idempotently", async () => {
    const user = await readFile(`${SEED_DIR}/001_user.sql`, "utf8");
    expect(user).toContain("ada@example.com");
    expect(user).toContain("INSERT INTO apiome.users");
    expect(user).toContain("ON CONFLICT");

    const tenant = await readFile(`${SEED_DIR}/002_tenant.sql`, "utf8");
    expect(tenant).toContain("acme-corp");

    const apiKey = await readFile(`${SEED_DIR}/005_api_key.sql`, "utf8");
    expect(apiKey).toContain("sk_devseed00...");

    const license = await readFile(`${SEED_DIR}/004_license.sql`, "utf8");
    expect(license).toContain("INSERT INTO apiome.licenses");
  });

  it("seeds the multi-tenant fixture: one user in three tenants with diverging roles/licenses", async () => {
    const fixture = await readFile(`${SEED_DIR}/007_multitenant.sql`, "utf8");

    // One user across three distinct tenants (OLO-6.4, #4221).
    expect(fixture).toContain("grace@example.com");
    expect(fixture).toContain("aurora-labs");
    expect(fixture).toContain("borealis-studio");
    expect(fixture).toContain("cascade-foundation");

    // Built-in roles must be seeded before the granular role assignments resolve.
    expect(fixture).toContain("apiome.seed_builtin_roles");
    expect(fixture).toContain("INSERT INTO apiome.tenant_user_roles");

    // Owner is expressed via the authoritative tenant_administrators signal.
    expect(fixture).toContain("INSERT INTO apiome.tenant_administrators");

    // Distinct license tiers attached per tenant (Free / Paid / Sponsor).
    expect(fixture).toContain("INSERT INTO apiome.tenant_licenses");
    expect(fixture).toMatch(/l\.name = 'Free'/);
    expect(fixture).toMatch(/l\.name = 'Paid'/);
    expect(fixture).toMatch(/l\.name = 'Sponsor'/);

    // Idempotent, like every other dev seed file.
    expect(fixture).toContain("ON CONFLICT");
  });
});
