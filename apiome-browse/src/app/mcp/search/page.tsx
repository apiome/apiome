import { searchPublicMcpCatalog } from '../../../../lib/db/helper';
import { sanitizeSearchInput } from '../../utils/searchValidation';
import { coerceSortMode } from '../../../../lib/mcpSort';
import { McpSearchClient } from './McpSearchClient';

export const dynamic = 'force-dynamic';

export default async function McpSearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; sort?: string }>;
}) {
  const { q, sort } = await searchParams;
  const query = sanitizeSearchInput(q || '');
  // Idle (empty query) → grade-led; with a term → relevance, unless the URL pins an explicit mode.
  const sortMode = coerceSortMode(sort, query);
  const results = query ? await searchPublicMcpCatalog(query, sortMode) : [];

  return <McpSearchClient initialQuery={query} initialSort={sortMode} initialResults={results} />;
}
