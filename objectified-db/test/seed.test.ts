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
    ]);
  });
});

describe("dev seed contents", () => {
  it("inserts the documented sample identifiers idempotently", async () => {
    const user = await readFile(`${SEED_DIR}/001_user.sql`, "utf8");
    expect(user).toContain("ada@example.com");
    expect(user).toContain("INSERT INTO odb.users");
    expect(user).toContain("ON CONFLICT");

    const tenant = await readFile(`${SEED_DIR}/002_tenant.sql`, "utf8");
    expect(tenant).toContain("acme-corp");

    const apiKey = await readFile(`${SEED_DIR}/005_api_key.sql`, "utf8");
    expect(apiKey).toContain("sk_devseed00...");

    const license = await readFile(`${SEED_DIR}/004_license.sql`, "utf8");
    expect(license).toContain("INSERT INTO odb.licenses");
  });
});
