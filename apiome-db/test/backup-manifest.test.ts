import { describe, expect, it } from "vitest";

import {
  buildManifest,
  parseManifest,
  serializeManifest,
  sha256,
  verifyArtifactIntegrity,
} from "../src/backup/manifest.js";
import { CliError } from "../src/errors.js";

const artifactBytes = Buffer.from("artifact contents", "utf8");

function sampleManifest() {
  return buildManifest({
    id: "tenant-acme-20260623T094730Z",
    kind: "tenant",
    tenant: "acme",
    createdAt: "2026-06-23T09:47:30.000Z",
    rpoMarker: "2026-06-23T09:40:00.000Z",
    artifact: "tenant-acme-20260623T094730Z.json.enc",
    artifactBytes,
    encrypted: true,
    tableCounts: { data_record: 5 },
  });
}

describe("buildManifest", () => {
  it("captures size + checksum and normalizes optional fields", () => {
    const m = sampleManifest();
    expect(m.sizeBytes).toBe(artifactBytes.length);
    expect(m.sha256).toBe(sha256(artifactBytes));
    expect(m.tenant).toBe("acme");
    expect(m.project).toBeNull();
    expect(m.tableCounts).toEqual({ data_record: 5 });
  });
});

describe("serialize/parse round-trip", () => {
  it("survives a JSON round-trip", () => {
    const m = sampleManifest();
    expect(parseManifest(serializeManifest(m))).toEqual(m);
  });

  it("defaults missing optional fields", () => {
    const parsed = parseManifest(
      JSON.stringify({
        id: "x",
        kind: "full",
        createdAt: "2026-06-23T00:00:00Z",
        artifact: "x.dump",
        sha256: "abc",
      }),
    );
    expect(parsed.tenant).toBeNull();
    expect(parsed.project).toBeNull();
    expect(parsed.encrypted).toBe(false);
    expect(parsed.tableCounts).toEqual({});
  });
});

describe("parseManifest validation", () => {
  it("rejects non-JSON", () => {
    expect(() => parseManifest("{not json")).toThrow(CliError);
  });
  it("rejects non-objects", () => {
    expect(() => parseManifest("[]")).toThrow(/must be a JSON object/i);
  });
  it("rejects missing required fields", () => {
    expect(() => parseManifest(JSON.stringify({ kind: "full" }))).toThrow(/missing required field/i);
  });
  it("rejects unknown kinds", () => {
    expect(() =>
      parseManifest(
        JSON.stringify({ id: "x", kind: "weird", createdAt: "t", artifact: "a", sha256: "s" }),
      ),
    ).toThrow(/unknown kind/i);
  });
});

describe("verifyArtifactIntegrity", () => {
  it("passes for matching bytes and fails for altered bytes", () => {
    const m = sampleManifest();
    expect(verifyArtifactIntegrity(m, artifactBytes)).toBe(true);
    expect(verifyArtifactIntegrity(m, Buffer.from("tampered"))).toBe(false);
  });
});
