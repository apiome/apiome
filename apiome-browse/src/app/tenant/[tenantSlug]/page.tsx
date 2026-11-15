import { notFound } from "next/navigation";
import { getPublicTenantBySlug, getPublicProjectsForTenant } from "../../../../lib/db/helper";
import { TenantClient } from "./TenantClient";
import { ReaderStatus } from "../../components/ReaderStatus";

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

  return (
    <>
      <div className="mx-auto flex max-w-[1480px] justify-end px-4 pt-4 sm:px-6 lg:px-8">
        <ReaderStatus tenantSlug={tenantSlug} returnTo={`/tenant/${tenantSlug}`} />
      </div>
      <TenantClient tenant={tenant} projects={projects} tenantSlug={tenantSlug} />
    </>
  );
}

