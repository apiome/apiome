import { notFound } from "next/navigation";
import {
  getPublicChangelogsForProject,
  getPublicProjectBySlug,
  getPublicVersionsForProject,
} from "../../../../../lib/db/helper";
import type { Severity } from "../../../../../lib/changelog/types";
import { ProjectClient } from "./ProjectClient";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string }>;
}) {
  const { tenantSlug, projectSlug } = await params;
  const project = await getPublicProjectBySlug(tenantSlug, projectSlug);

  if (!project) {
    notFound();
  }

  const [versions, changelogs] = await Promise.all([
    getPublicVersionsForProject(tenantSlug, projectSlug),
    getPublicChangelogsForProject(tenantSlug, projectSlug),
  ]);

  // Classified max severity per version label, for the timeline pills (CTG-3.2, #4476).
  const changelogSeverities: Record<string, Severity> = {};
  for (const row of changelogs) {
    if (row.maxSeverity) {
      changelogSeverities[row.versionLabel] = row.maxSeverity;
    }
  }

  return (
    <ProjectClient
      project={project}
      versions={versions}
      changelogSeverities={changelogSeverities}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
    />
  );
}
