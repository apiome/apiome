import { describe, expect, it } from "vitest";

import type { VersionSchema } from "../src/generated/models.js";
import { buildTagsByRevisionId, formatVersionsListHumanLines } from "../src/lib/versions/list-format.js";

function V(partial: Partial<VersionSchema> & Pick<VersionSchema, "id" | "project_id" | "version_id">): VersionSchema {
  return {
    enabled: true,
    published: false,
    ...partial,
  };
}

describe("versions list human table snapshots (#3208)", () => {
  it("matches issue-style columns (80 cols) with tags joined client-side", () => {
    const revDraft = "11111111-1111-1111-1111-111111111111";
    const revPub = "22222222-2222-2222-2222-222222222222";
    const revPubFrozen = "33333333-3333-3333-3333-333333333333";
    const revArchived = "44444444-4444-4444-4444-444444444444";

    const versions: VersionSchema[] = [
      V({
        id: revDraft,
        project_id: "p1",
        version_id: "2.2.0-rc.1",
        published: false,
        published_at: null,
        author: "morgan@example.com",
      }),
      V({
        id: revPub,
        project_id: "p1",
        version_id: "2.1.0",
        published: true,
        published_at: "2026-05-04T12:00:00.000Z",
        author: "kenji@example.com",
      }),
      V({
        id: revPubFrozen,
        project_id: "p1",
        version_id: "2.0.0",
        published: true,
        publishedImmutable: true,
        published_at: "2026-02-18T08:00:00.000Z",
        author: "kenji@example.com",
      }),
      V({
        id: revArchived,
        project_id: "p1",
        version_id: "1.4.0",
        published: true,
        published_at: "2025-11-02T00:00:00.000Z",
        lifecycle: "archived",
        author: null,
      }),
    ];

    const tagsByRevisionId = buildTagsByRevisionId([
      {
        id: "t1",
        project_id: "p1",
        version_id: revDraft,
        name: "next",
        immutable: false,
        protected: false,
      },
      {
        id: "t2",
        project_id: "p1",
        version_id: revPub,
        name: "stable",
        immutable: false,
        protected: false,
      },
      {
        id: "t3",
        project_id: "p1",
        version_id: revPub,
        name: "latest",
        immutable: false,
        protected: false,
      },
    ]);

    const lines = formatVersionsListHumanLines({
      versions,
      tagsByRevisionId,
      projectLabel: "payments-api",
      truncated: true,
      totalAfterPipeline: 8,
      useGlyphForFrozen: false,
      freezeGlyph: "",
      freezeBracket: " [frozen]",
    });
    expect(lines.join("\n")).toMatchSnapshot();
  });

  it("keeps columns stable when frozen glyph is ANSI-colored", () => {
    const revPubFrozen = "33333333-3333-3333-3333-333333333333";
    const versions: VersionSchema[] = [
      V({
        id: revPubFrozen,
        project_id: "p1",
        version_id: "2.0.0",
        published: true,
        publishedImmutable: true,
        published_at: "2026-02-18T08:00:00.000Z",
        author: "morgan@example.com",
      }),
    ];
    const lines = formatVersionsListHumanLines({
      versions,
      tagsByRevisionId: new Map(),
      projectLabel: "payments-api",
      truncated: false,
      totalAfterPipeline: 1,
      useGlyphForFrozen: true,
      freezeGlyph: "\u001b[36m❄\u001b[39m",
      freezeBracket: " [frozen]",
    });

    expect(lines[1]).toContain("\u001b[36m❄\u001b[39m");
    expect(lines[1]).toContain("morgan@example.com");
  });
});
