/**
 * One entity's graph edges, with labels (CDG-3.4, #5969).
 *
 * Proxies `GET /v1/graph/{slug}/entities/{kind}/{id}/edges?labels=true&direction=&kind=&provenance=&limit=&offset=`.
 * The kind and id are validated so a crafted segment cannot reach another REST path.
 */

import { NextRequest, NextResponse } from 'next/server';
import { isGraphId, isGraphNodeKind } from '@lib/graph';
import { forwardGraphRequest, forwardedQuery, graphUrl, resolveGraphTenant } from '@lib/graph-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await context.params;
  if (!isGraphNodeKind(kind) || !isGraphId(id)) {
    return NextResponse.json({ success: false, error: 'Unknown entity.' }, { status: 400 });
  }
  const resolved = await resolveGraphTenant();
  if ('error' in resolved) return resolved.error;
  const params = new URLSearchParams(request.nextUrl.searchParams);
  params.set('labels', 'true');
  const query = forwardedQuery(params, {
    labels: 'single',
    direction: 'single',
    kind: 'repeat',
    provenance: 'repeat',
    limit: 'single',
    offset: 'single',
  });
  return forwardGraphRequest(graphUrl(resolved.slug, `entities/${kind}/${id}/edges${query}`), {
    method: 'GET',
    user: resolved.user,
    unavailable: 'The dependency graph is unavailable right now.',
  });
}
