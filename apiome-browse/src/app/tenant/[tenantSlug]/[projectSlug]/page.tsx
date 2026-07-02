import { notFound } from "next/navigation";
import { getPublicProjectBySlug, getPublicVersionsForProject } from "../../../../../lib/db/helper";
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

  const versions = await getPublicVersionsForProject(tenantSlug, projectSlug);

  return <ProjectClient project={project} versions={versions} tenantSlug={tenantSlug} projectSlug={projectSlug} />;
}
