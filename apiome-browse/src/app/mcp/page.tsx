import { getPublicMcpEndpointsByHost } from '../../../lib/db/helper';
import { McpBrowseClient } from './McpBrowseClient';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'MCP Catalog — Apiome',
  description:
    'Browse published public Model Context Protocol servers by site, ranked by quality grade.',
};

export default async function McpBrowsePage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  // DBP-1.27: the index is paged — 100 servers per page, `?page=2` for the next.
  const raw = (await searchParams).page;
  const page = Number.parseInt((Array.isArray(raw) ? raw[0] : raw) ?? '1', 10);
  const index = await getPublicMcpEndpointsByHost(Number.isFinite(page) ? page : 1);
  return <McpBrowseClient index={index} />;
}
