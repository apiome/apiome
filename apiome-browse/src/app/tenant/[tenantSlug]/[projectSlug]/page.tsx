import { notFound } from "next/navigation";
import { loadProjectPage } from "../../../../../lib/db/routeLoaders";
import type { Severity } from "../../../../../lib/changelog/types";
import { ProjectClient } from "./ProjectClient";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string }>;
}) {
  const { tenantSlug, projectSlug } = await params;
  // Two statements (DBP-1.27): the project with its facts, then its newest versions, each with its
  // classified severity.
  const data = await loadProjectPage(tenantSlug, projectSlug);

  if (!data) {
    notFound();
  }
  const { project, versions } = data;

  // Classified max severity per version label, for the timeline pills (CTG-3.2, #4476).
  const changelogSeverities: Record<string, Severity> = {};
  for (const row of versions) {
    if (row.max_severity) {
      changelogSeverities[row.version_id] = row.max_severity;
    }
  }

  return (
    <ProjectClient
      project={project}
      versions={versions}
      versionCount={project.version_count}
      changelogSeverities={changelogSeverities}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
    />
  );
}
