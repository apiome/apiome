import { notFound } from 'next/navigation';
import { loadMcpCollectionPage } from '../../../../../../lib/db/routeLoaders';
import { McpCollectionClient } from './McpCollectionClient';

export const dynamic = 'force-dynamic';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ tenantSlug: string; collectionSlug: string }>;
}) {
  const { tenantSlug, collectionSlug } = await params;
  // Shared with the page through React's cache(): the collection is read once per request.
  const collection = await loadMcpCollectionPage(tenantSlug, collectionSlug);
  if (!collection) {
    return { title: 'Collection not found — Apiome' };
  }
  return {
    title: `${collection.name} — MCP Catalog — Apiome`,
    description:
      collection.description ??
      `Published curated collection of MCP servers from ${collection.tenant_name}.`,
  };
}

export default async function McpCollectionPage({
  params,
}: {
  params: Promise<{ tenantSlug: string; collectionSlug: string }>;
}) {
  const { tenantSlug, collectionSlug } = await params;
  const collection = await loadMcpCollectionPage(tenantSlug, collectionSlug);
  if (!collection) {
    notFound();
  }
  return <McpCollectionClient collection={collection} />;
}
