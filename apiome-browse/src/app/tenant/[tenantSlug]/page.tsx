import { notFound } from "next/navigation";
import { loadTenantPage } from "../../../../lib/db/routeLoaders";
import { TenantClient } from "./TenantClient";
import { ReaderStatus } from "../../components/ReaderStatus";

export default async function TenantPage({
  params,
}: {
  params: Promise<{ tenantSlug: string }>;
}) {
  const { tenantSlug } = await params;
  // Three statements, run together (DBP-1.27): the organization, its projects, its products.
  const data = await loadTenantPage(tenantSlug);

  if (!data) {
    notFound();
  }
  const { tenant, projects, products } = data;

  return (
    <>
      <div className="mx-auto flex max-w-[1480px] justify-end px-4 pt-4 sm:px-6 lg:px-8">
        <ReaderStatus tenantSlug={tenantSlug} returnTo={`/tenant/${tenantSlug}`} />
      </div>
      <TenantClient tenant={tenant} projects={projects} products={products} tenantSlug={tenantSlug} />
    </>
  );
}
