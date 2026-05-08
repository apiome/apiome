import { describe, expect, it } from "vitest";

import type { VersionSchema } from "../src/generated/models.js";
import {
  applyVersionsListPipeline,
  compareSemverVersionIdsAsc,
  parseVersionStateFilter,
  parseVersionsSortField,
  versionStateMembership,
} from "../src/lib/versions/list-query.js";

function V(partial: Partial<VersionSchema> & Pick<VersionSchema, "id" | "project_id" | "version_id">): VersionSchema {
  return {
    enabled: true,
    published: false,
    ...partial,
  };
}

describe("versions list semver sort (#3208)", () => {
  it("orders semver ids ascending", () => {
    expect(compareSemverVersionIdsAsc("1.0.0", "2.0.0")).toBeLessThan(0);
    expect(compareSemverVersionIdsAsc("v2.1.0", "2.0.9")).toBeGreaterThan(0);
    expect(compareSemverVersionIdsAsc("2.2.0-rc.1", "2.2.0")).toBeLessThan(0);
  });

  it("defaults to version descending (newest semver first)", () => {
    const rows = [
      V({ id: "a", project_id: "p", version_id: "1.0.0" }),
      V({ id: "b", project_id: "p", version_id: "2.0.0" }),
      V({ id: "c", project_id: "p", version_id: "1.5.0" }),
    ];
    const out = applyVersionsListPipeline(rows, {
      stateFilter: undefined,
      sortField: "version",
      reverse: false,
    });
    expect(out.map((x) => x.version_id)).toEqual(["2.0.0", "1.5.0", "1.0.0"]);
  });

  it("--reverse flips version order", () => {
    const rows = [
      V({ id: "a", project_id: "p", version_id: "1.0.0" }),
      V({ id: "b", project_id: "p", version_id: "2.0.0" }),
    ];
    const out = applyVersionsListPipeline(rows, {
      stateFilter: undefined,
      sortField: "version",
      reverse: true,
    });
    expect(out.map((x) => x.version_id)).toEqual(["1.0.0", "2.0.0"]);
  });
});

describe("versions list state filter (#3208)", () => {
  it("parses comma-separated states", () => {
    const s = parseVersionStateFilter(" draft , FROZEN ");
    expect(s?.has("draft")).toBe(true);
    expect(s?.has("frozen")).toBe(true);
    expect(s?.size).toBe(2);
  });

  it("rejects unknown state tokens", () => {
    expect(() => parseVersionStateFilter("draft,solid")).toThrow(/Invalid --state/);
  });

  it("infers archived from lifecycle or disabled flag", () => {
    const a = V({
      id: "1",
      project_id: "p",
      version_id: "1.0.0",
      lifecycle: "archived",
    });
    expect(versionStateMembership(a)).toEqual(new Set(["archived"]));
    const b = V({ id: "2", project_id: "p", version_id: "2.0.0", enabled: false });
    expect(versionStateMembership(b)).toEqual(new Set(["archived"]));
  });

  it("frozen published rows match frozen and published", () => {
    const v = V({
      id: "x",
      project_id: "p",
      version_id: "2.1.0",
      published: true,
      publishedImmutable: true,
    });
    const m = versionStateMembership(v);
    expect(m.has("frozen")).toBe(true);
    expect(m.has("published")).toBe(true);
  });

  it("filters with OR semantics", () => {
    const rows = [
      V({ id: "d", project_id: "p", version_id: "0.9.0", published: false }),
      V({ id: "p", project_id: "p", version_id: "1.0.0", published: true }),
      V({ id: "a", project_id: "p", version_id: "0.5.0", lifecycle: "archived" }),
    ];
    const draftOrPub = parseVersionStateFilter("draft,published");
    if (draftOrPub === undefined) throw new Error("expected filter");
    const out = applyVersionsListPipeline(rows, {
      stateFilter: draftOrPub,
      sortField: "version",
      reverse: false,
    });
    expect(out.map((x) => x.id).sort()).toEqual(["d", "p"]);
  });
});

describe("versions list sort fields (#3208)", () => {
  it("parses sort flag", () => {
    expect(parseVersionsSortField(undefined)).toBe("version");
    expect(parseVersionsSortField("published_at")).toBe("published_at");
    expect(() => parseVersionsSortField("semver")).toThrow(/Invalid --sort/);
  });

  it("sorts by published_at descending by default", () => {
    const rows = [
      V({
        id: "a",
        project_id: "p",
        version_id: "1.0.0",
        published: true,
        published_at: "2026-02-18T00:00:00Z",
      }),
      V({
        id: "b",
        project_id: "p",
        version_id: "2.0.0",
        published: true,
        published_at: "2026-05-04T00:00:00Z",
      }),
    ];
    const out = applyVersionsListPipeline(rows, {
      stateFilter: undefined,
      sortField: "published_at",
      reverse: false,
    });
    expect(out.map((x) => x.version_id)).toEqual(["2.0.0", "1.0.0"]);
  });

  it("applies tie-breaker direction with the primary sort", () => {
    const rows = [
      V({
        id: "a",
        project_id: "p",
        version_id: "1.0.0",
        published: true,
        published_at: "2026-05-04T00:00:00Z",
      }),
      V({
        id: "b",
        project_id: "p",
        version_id: "2.0.0",
        published: true,
        published_at: "2026-05-04T00:00:00Z",
      }),
    ];

    const outDesc = applyVersionsListPipeline(rows, {
      stateFilter: undefined,
      sortField: "published_at",
      reverse: false,
    });
    expect(outDesc.map((x) => x.version_id)).toEqual(["2.0.0", "1.0.0"]);

    const outAsc = applyVersionsListPipeline(rows, {
      stateFilter: undefined,
      sortField: "published_at",
      reverse: true,
    });
    expect(outAsc.map((x) => x.version_id)).toEqual(["1.0.0", "2.0.0"]);
  });
});
