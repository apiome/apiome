import { CatalogItemDetailClient } from './CatalogItemDetailClient';

/**
 * Catalog item detail route (MFI-23.9, #4018): `/ade/dashboard/catalog/{id}`.
 *
 * A thin server wrapper that unwraps the dynamic `id` and renders the client detail view, mirroring
 * the other dashboard detail routes. The view itself (source material, provenance, normalized
 * summary, quality/lint) is rendered client-side from the `/api/catalog/{id}` proxy.
 */
export default async function CatalogItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CatalogItemDetailClient itemId={id} />;
}
