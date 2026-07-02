import { notFound } from "next/navigation";
import { getPublicTenantBySlug, getPublicProjectsForTenant } from "../../../../lib/db/helper";
import { TenantClient } from "./TenantClient";

export default async function TenantPage({
  params,
}: {
  params: Promise<{ tenantSlug: string }>;
}) {
  const { tenantSlug } = await params;
  const tenant = await getPublicTenantBySlug(tenantSlug);

  if (!tenant) {
    notFound();
  }

  const projects = await getPublicProjectsForTenant(tenantSlug);

  return <TenantClient tenant={tenant} projects={projects} tenantSlug={tenantSlug} />;
}

