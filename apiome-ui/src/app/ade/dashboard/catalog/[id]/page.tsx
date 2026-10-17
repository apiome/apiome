import { getAuthSession } from '@lib/auth/server-session';
import { getCommercialAccessForSession } from '@lib/db/commercial-access';
import { buildDesignerCatalogPreviewHref } from '@lib/external-links';
import { CatalogItemDetailClient } from './CatalogItemDetailClient';

/**
 * Catalog item detail route (MFI-23.9, #4018): `/ade/dashboard/catalog/{id}`.
 *
 * A thin server wrapper that unwraps the dynamic `id` and renders the client detail view, mirroring
 * the other dashboard detail routes. The view itself (source material, provenance, normalized
 * summary, quality/lint) is rendered client-side from the `/api/catalog/{id}` proxy.
 *
 * It also resolves, on the server, whether the tenant is entitled to the Designer suite: only then
 * does the header offer "Open in Designer", the Studio's read-only preview (MFI-23.12, #4021).
 */
export default async function CatalogItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await getAuthSession();
  const { entitledFlags } = session?.user
    ? await getCommercialAccessForSession()
    : { entitledFlags: [] as string[] };
  const designerPreviewHref = buildDesignerCatalogPreviewHref(id, new Set(entitledFlags));
  return <CatalogItemDetailClient itemId={id} designerPreviewHref={designerPreviewHref} />;
}
