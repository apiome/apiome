import { notFound } from "next/navigation";
import { getPublicVersionDetails } from "../../../../../../lib/db/helper";
import { VersionClient } from "./VersionClient";
export default async function VersionPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; projectSlug: string; versionSlug: string }>;
}) {
  const { tenantSlug, projectSlug, versionSlug } = await params;
  const version = await getPublicVersionDetails(tenantSlug, projectSlug, versionSlug);
  if (!version) {
    notFound();
  }
  const restApiBaseUrl = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';
  return (
    <VersionClient
      version={version}
      tenantSlug={tenantSlug}
      projectSlug={projectSlug}
      versionSlug={versionSlug}
      restApiBaseUrl={restApiBaseUrl}
    />
  );
}

