import { notFound } from "next/navigation";
import {
  getPublicChangelogsForProject,
  getPublicProjectBySlug,
  getPublicVersionsForProject,
} from "../../../../../../lib/db/helper";
import { CompareClient } from "./CompareClient";

export default async function ComparePage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string }>;
  searchParams: Promise<{ v1?: string; v2?: string; focus?: string }>;
}) {
  const { tenantSlug, projectSlug } = await params;
  const { v1, v2, focus } = await searchParams;
  const project = await getPublicProjectBySlug(tenantSlug, projectSlug);

  if (!project) {
    notFound();
  }

  const [versions, changelogs] = await Promise.all([
    getPublicVersionsForProject(tenantSlug, projectSlug),
    getPublicChangelogsForProject(tenantSlug, projectSlug),
  ]);

  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

  return (
    <CompareClient
      project={project}
      versions={versions}
      changelogs={changelogs}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
      restApiBaseUrl={restApiBaseUrl}
      initialV1={v1}
      initialV2={v2}
      initialFocus={focus}
    />
  );
}
