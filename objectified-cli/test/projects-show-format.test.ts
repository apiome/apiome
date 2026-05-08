import { describe, expect, it } from "vitest";

import type { ProjectSchema, VersionSchema, WorkflowAuditEntryOut } from "../src/lib/client.js";

import {
  formatProjectsShowHumanLines,
  formatWorkflowAuditActivityLine,
  revisionToVersionDisplayMap,
  summarizeVersionLifecycle,
} from "../src/lib/projects/show-format.js";

describe("projects show formatting (#3203)", () => {
  const project: ProjectSchema = {
    id: "33333333-4444-5555-6666-777777777777",
    tenant_id: "t1",
    name: "Payments API",
    slug: "payments-api",
    enabled: true,
    description: "Inbound charges.",
    creator_email: "kenji@objectified.dev",
    created_at: "2024-08-19T10:00:00Z",
    updated_at: "2026-04-02T15:00:00Z",
    metadata: { domain: "finance" },
  };

  it("summarizes lifecycle buckets", () => {
    const versions: VersionSchema[] = [
      {
        id: "r1",
        project_id: project.id,
        version_id: "2.1.0",
        published: true,
        published_at: "2026-05-04T12:00:00Z",
        enabled: true,
      },
      {
        id: "r2",
        project_id: project.id,
        version_id: "2.2.0-rc.1",
        published: false,
        enabled: true,
      },
      {
        id: "r3",
        project_id: project.id,
        version_id: "1.0.0",
        lifecycle: "archived",
        published: true,
        enabled: true,
      },
    ];
    const s = summarizeVersionLifecycle(versions);
    expect(s.total).toBe(3);
    expect(s.published).toBe(1);
    expect(s.draft).toBe(1);
    expect(s.archived).toBe(1);
    expect(s.latestPublished?.versionLabel).toBe("v2.1.0");
  });

  it("renders workflow audit lines using revision map", () => {
    const versions: VersionSchema[] = [
      {
        id: "rev-aaa",
        project_id: project.id,
        version_id: "2.1.0",
        published: true,
        enabled: true,
      },
    ];
    const map = revisionToVersionDisplayMap(versions);
    const entry: WorkflowAuditEntryOut = {
      id: "a",
      tenantId: "t",
      projectId: project.id,
      versionId: "rev-aaa",
      action: "version.push",
      outcome: "success",
      actorId: "11111111-2222-3333-4444-555555555555",
      createdAt: "2026-05-06T12:00:00Z",
      detail: null,
    };
    const line = formatWorkflowAuditActivityLine(entry, map, Date.parse("2026-05-08T12:00:00Z"));
    expect(line).toContain("versions push");
    expect(line).toContain("v2.1.0");
  });

  it("includes title and key rows in human output", () => {
    const lines = formatProjectsShowHumanLines({
      project,
      tenantSlug: "acme-corp",
      versions: [],
      tags: [],
      activity: [],
      titleBold: (s) => s,
      separator: "-".repeat(61),
      now: new Date("2026-05-08T12:00:00Z"),
    });
    expect(lines.some((l) => l.includes("Payments API") && l.includes("payments-api"))).toBe(true);
    expect(lines.some((l) => l.includes("Tenant") && l.includes("acme-corp"))).toBe(true);
    expect(lines.some((l) => l.includes("finance"))).toBe(true);
  });
});
