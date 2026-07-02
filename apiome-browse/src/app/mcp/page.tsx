import { getPublicMcpEndpointsByHost } from '../../../lib/db/helper';
import { McpBrowseClient } from './McpBrowseClient';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'MCP Catalog — Apiome',
  description:
    'Browse published public Model Context Protocol servers by site, ranked by quality grade.',
};

export default async function McpBrowsePage() {
  const groups = await getPublicMcpEndpointsByHost();
  return <McpBrowseClient groups={groups} />;
}
