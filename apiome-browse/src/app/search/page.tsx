import type { Metadata } from 'next';
import { searchPublicMcpCatalog } from '../../../lib/db/helper';
import { runCatalogSearch, runHitVersionsLookup } from '../../../lib/db/search';
import { resolveSearchRequest, type SearchUrlState } from '../../../lib/search/params';
import { textNeedles } from '../../../lib/search/query';
import { sanitizeSearchInput } from '../utils/searchValidation';
import { SearchClient } from './SearchClient';

export const dynamic = 'force-dynamic';

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The MCP engine takes plain words; operators belong to the catalog engine. */
function mcpQueryFor(request: ReturnType<typeof resolveSearchRequest>): string {
  return textNeedles(request.parsed).join(' ');
}

export async function generateMetadata({ searchParams }: { searchParams: Promise<RawParams> }): Promise<Metadata> {
  const q = sanitizeSearchInput(first((await searchParams).q) ?? '').trim();
  return {
    title: q ? `${q} — Search · Apiome Browse` : 'Search · Apiome Browse',
    description: 'Search operations, schemas, projects and organizations across every published public API specification.',
  };
}

export default async function SearchPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const sp = await searchParams;
  const state: SearchUrlState = {
    q: sanitizeSearchInput(first(sp.q) ?? ''),
    scope: first(sp.scope),
    type: sp.type,
    org: sp.org,
    method: sp.method,
    format: sp.format,
    paradigm: sp.paradigm,
    severity: sp.severity,
    after: first(sp.after),
    before: first(sp.before),
    sort: first(sp.sort),
    page: first(sp.page),
    all: first(sp.all),
  };
  const request = resolveSearchRequest(state);
  const mcpQuery = mcpQueryFor(request);

  const [response, mcpHits] = await Promise.all([
    runCatalogSearch(request),
    mcpQuery ? searchPublicMcpCatalog(mcpQuery, 'relevance') : Promise.resolve([]),
  ]);

  // BDX-2.6: one follow-up query fills the version quick-switch menus of the page's hits.
  const hitVersions = await runHitVersionsLookup(response.rows);

  return <SearchClient request={request} response={response} hitVersions={hitVersions} mcpHits={mcpHits} mcpQuery={mcpQuery} />;
}
