import { describe, expect, it } from "vitest";

import {
  didYouMeanSlugs,
  normalizeProjectRef,
  projectRefLooksLikeUuid,
} from "../src/lib/resolve.js";

describe("project ref resolution helpers (#3203)", () => {
  it("normalizes whitespace", () => {
    expect(normalizeProjectRef("  payments-api \n")).toBe("payments-api");
  });

  it("detects canonical lowercase UUIDs", () => {
    expect(projectRefLooksLikeUuid("33333333-4444-5555-6666-777777777777")).toBe(true);
    expect(projectRefLooksLikeUuid("payments-api")).toBe(false);
    expect(projectRefLooksLikeUuid("not-a-uuid")).toBe(false);
  });

  it("ranks slug suggestions by Levenshtein distance", () => {
    const slugs = ["payments-api", "pets-api", "billing-portal"];
    const paySuggest = didYouMeanSlugs("payment-api", slugs);
    expect(paySuggest[0]).toBe("payments-api");
    expect(paySuggest.length).toBeGreaterThanOrEqual(1);
    expect(didYouMeanSlugs("pets-ap", slugs)).toContain("pets-api");
  });
});
