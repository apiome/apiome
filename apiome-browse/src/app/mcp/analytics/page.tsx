import { getPublicCatalogInsight } from '../../../../lib/db/helper';
import { CatalogAnalyticsClient } from '../CatalogAnalyticsClient';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'MCP Catalog Analytics — Apiome',
  description:
    'How the published, public Model Context Protocol servers in the directory break down by category, transport, and quality grade.',
};

/**
 * Public catalog analytics page (V2-MCP-32.1 / MCAT-18.1). Server component: reads the reduced
 * public roll-up over `apiome.mcp_v_public_endpoints` (published + public only) and hands it to the
 * client renderer, which owns the tiles and the empty state.
 */
export default async function McpCatalogAnalyticsPage() {
  const insight = await getPublicCatalogInsight();
  return <CatalogAnalyticsClient insight={insight} />;
}
