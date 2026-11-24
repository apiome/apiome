import { notFound } from "next/navigation";
import { loadComparePage } from "../../../../../../lib/db/routeLoaders";
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
  // Three statements (DBP-1.27): the project, its version labels, and the stored changelog of the
  // pair being compared — without entries; the chips read its counts and severity. Choosing other
  // versions navigates to `?v1=&v2=`, which renders this page again with that pair's row.
  const data = await loadComparePage(tenantSlug, projectSlug, v1, v2);

  if (!data) {
    notFound();
  }

  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

  return (
    <CompareClient
      project={data.project}
      versions={data.versions}
      changelogs={data.changelogs}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
      restApiBaseUrl={restApiBaseUrl}
      initialV1={v1}
      initialV2={v2}
      initialFocus={focus}
    />
  );
}
