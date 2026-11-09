import { searchPublicMcpCatalog, searchRegistryForPublicCatalog } from '../../../../lib/db/helper';
import { sanitizeSearchInput } from '../../utils/searchValidation';
import { coerceSortMode } from '../../../../lib/mcpSort';
import { McpSearchClient } from './McpSearchClient';

export const dynamic = 'force-dynamic';

export default async function McpSearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; sort?: string; registry?: string }>;
}) {
  const { q, sort, registry } = await searchParams;
  const query = sanitizeSearchInput(q || '');
  // Idle (empty query) → grade-led; with a term → relevance, unless the URL pins an explicit mode.
  const sortMode = coerceSortMode(sort, query);
  // Federated search (V2-MCP-26.4): `registry=1` also searches the MCP registry.
  const includeRegistry = registry === '1';
  const results = query ? await searchPublicMcpCatalog(query, sortMode) : [];
  const registryResult =
    query && includeRegistry
      ? await searchRegistryForPublicCatalog(
          query,
          results.map((hit) => hit.endpoint_id)
        )
      : null;

  return (
    <McpSearchClient
      initialQuery={query}
      initialSort={sortMode}
      initialResults={results}
      includeRegistry={includeRegistry}
      registryResult={registryResult}
    />
  );
}
