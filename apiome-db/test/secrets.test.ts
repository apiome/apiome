import bcrypt from "bcrypt";
import { describe, expect, it } from "vitest";

import {
  API_KEY_PREFIX,
  apiKeyPrefix,
  generateApiKey,
  generatePassword,
  hashApiKey,
  hashPassword,
} from "../src/secrets.js";

describe("API key generation (must match apiome-ui / apiome-rest)", () => {
  it("produces `sk_` + 64 hex chars", () => {
    const key = generateApiKey();
    expect(key.startsWith(API_KEY_PREFIX)).toBe(true);
    expect(key).toMatch(/^sk_[0-9a-f]{64}$/);
    expect(key.length).toBe(67);
  });

  it("derives the lookup prefix as first 12 chars + '...' (REST validate_api_key)", () => {
    const key = "sk_abcdef0123456789";
    expect(apiKeyPrefix(key)).toBe("sk_abcdef012...");
    // Mirrors the REST formula exactly.
    expect(apiKeyPrefix(key)).toBe(`${key.slice(0, 12)}...`);
  });

  it("hashes the full key with bcrypt so REST's bcrypt.checkpw(rawKey, hash) succeeds", async () => {
    const key = generateApiKey();
    const hash = await hashApiKey(key);
    expect(hash.startsWith("$2")).toBe(true);
    expect(await bcrypt.compare(key, hash)).toBe(true);
    expect(await bcrypt.compare("sk_wrong", hash)).toBe(false);
  });
});

describe("password hashing", () => {
  it("produces a verifiable bcrypt hash", async () => {
    const hash = await hashPassword("hunter2");
    expect(hash.startsWith("$2")).toBe(true);
    expect(await bcrypt.compare("hunter2", hash)).toBe(true);
  });
});

describe("generatePassword", () => {
  it("returns a non-trivial, unique-ish secret", () => {
    const a = generatePassword();
    const b = generatePassword();
    expect(a.length).toBeGreaterThanOrEqual(12);
    expect(a).not.toBe(b);
  });
});
