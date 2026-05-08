import { describe, expect, it } from "vitest";

import { ObjectifiedCliError } from "../src/lib/errors.js";
import { EXIT_CODES } from "../src/lib/exit-codes.js";
import {
  buildSchemaFetchAcceptHeader,
  normalizeExpectSha256Hex,
  parseTenantProjectVersionRef,
} from "../src/lib/schema/schema-fetch-helpers.js";

describe("schema fetch helpers (#3247)", () => {
  it("parses tenant/project/version", () => {
    expect(parseTenantProjectVersionRef("  acme-corp/payments-api/2.1.0 ")).toEqual({
      tenantSlug: "acme-corp",
      projectSlug: "payments-api",
      versionSlug: "2.1.0",
    });
  });

  it("rejects fewer than three segments", () => {
    expect(() => parseTenantProjectVersionRef("acme/payments-api")).toThrow(ObjectifiedCliError);
    try {
      parseTenantProjectVersionRef("only-one");
    } catch (e) {
      expect(e).toBeInstanceOf(ObjectifiedCliError);
      expect((e as ObjectifiedCliError).exitCode).toBe(EXIT_CODES.MISUSE);
    }
  });

  it("rejects more than three segments", () => {
    expect(() => parseTenantProjectVersionRef("acme/payments-api/2.1.0/extra")).toThrow(
      ObjectifiedCliError,
    );
  });

  it("normalizes expect-sha256 hex", () => {
    const lower =
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    expect(normalizeExpectSha256Hex(`  ${lower.toUpperCase()}  `)).toBe(lower);
    expect(normalizeExpectSha256Hex(`0x${lower}`)).toBe(lower);
  });

  it("rejects invalid expect-sha256", () => {
    expect(() => normalizeExpectSha256Hex("gg")).toThrow(ObjectifiedCliError);
    expect(() => normalizeExpectSha256Hex("abcd")).toThrow(ObjectifiedCliError);
  });

  it("builds Accept for class + tag", () => {
    expect(
      buildSchemaFetchAcceptHeader({
        format: "yaml",
        className: "Charge",
        acceptTag: "tag:stable",
      }),
    ).toBe("tag:stable, application/yaml");
    expect(
      buildSchemaFetchAcceptHeader({
        format: "json",
        className: "Charge",
      }),
    ).toBe("application/json");
    expect(buildSchemaFetchAcceptHeader({ format: "json" })).toBe(undefined);
  });
});
