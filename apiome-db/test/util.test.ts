import { describe, expect, it } from "vitest";

import { isUuid, isValidEmail, isValidSlug, normalizeEmail, slugify } from "../src/util.js";

describe("isUuid", () => {
  it("accepts a v4 uuid and rejects non-uuids", () => {
    expect(isUuid("f47ac10b-58cc-4372-a567-0e02b2c3d479")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("acme")).toBe(false);
  });
});

describe("isValidSlug", () => {
  it("accepts lowercase hyphenated slugs", () => {
    expect(isValidSlug("acme")).toBe(true);
    expect(isValidSlug("acme-corp")).toBe(true);
    expect(isValidSlug("a1-b2-c3")).toBe(true);
  });
  it("rejects invalid slugs", () => {
    expect(isValidSlug("Acme")).toBe(false);
    expect(isValidSlug("acme_corp")).toBe(false);
    expect(isValidSlug("-acme")).toBe(false);
    expect(isValidSlug("acme-")).toBe(false);
    expect(isValidSlug("acme--corp")).toBe(false);
  });
});

describe("slugify", () => {
  it("normalizes display names into slugs", () => {
    expect(slugify("Acme Corp")).toBe("acme-corp");
    expect(slugify("  Hello, World!  ")).toBe("hello-world");
    expect(slugify("Already-Good")).toBe("already-good");
  });
});

describe("isValidEmail", () => {
  it("does basic shape validation", () => {
    expect(isValidEmail("a@b.com")).toBe(true);
    expect(isValidEmail("nope")).toBe(false);
    expect(isValidEmail("a@b")).toBe(false);
  });
});

describe("normalizeEmail", () => {
  it("lowercases and trims so casing/whitespace never split an account", () => {
    expect(normalizeEmail("Ada@Example.com")).toBe("ada@example.com");
    expect(normalizeEmail("  ADA@EXAMPLE.COM  ")).toBe("ada@example.com");
    expect(normalizeEmail("ada@example.com")).toBe("ada@example.com");
  });
  it("is idempotent", () => {
    const once = normalizeEmail("Ada@Example.com");
    expect(normalizeEmail(once)).toBe(once);
  });
});
