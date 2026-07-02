import { notFound } from "next/navigation";
import { getPublicProjectBySlug, getPublicVersionsForProject } from "../../../../../../lib/db/helper";
import { CompareClient } from "./CompareClient";

export default async function ComparePage({
  params,
  searchParams,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string }>;
  searchParams: Promise<{ v1?: string; v2?: string }>;
}) {
  const { tenantSlug, projectSlug } = await params;
  const { v1, v2 } = await searchParams;
  const project = await getPublicProjectBySlug(tenantSlug, projectSlug);

  if (!project) {
    notFound();
  }

  const versions = await getPublicVersionsForProject(tenantSlug, projectSlug);

  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

  return (
    <CompareClient
      project={project}
      versions={versions}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
      restApiBaseUrl={restApiBaseUrl}
      initialV1={v1}
      initialV2={v2}
    />
  );
}

