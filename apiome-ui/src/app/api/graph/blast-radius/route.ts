/**
 * The blast-radius query (CDG-3.4, #5969).
 *
 * Proxies `POST /v1/graph/{slug}/blast-radius`, forwarding only the fields REST accepts.
 */

import { NextRequest, NextResponse } from 'next/server';
import { isGraphNodeKind } from '@lib/graph';
import { forwardGraphRequest, graphUrl, resolveGraphTenant } from '@lib/graph-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ success: false, error: 'The request body is not JSON.' }, { status: 400 });
  }
  const entity = (body?.entity ?? {}) as Record<string, unknown>;
  if (!isGraphNodeKind(entity.kind) || typeof entity.id !== 'string' || !entity.id) {
    return NextResponse.json({ success: false, error: 'Pick an entity.' }, { status: 400 });
  }
  const resolved = await resolveGraphTenant();
  if ('error' in resolved) return resolved.error;
  const forwarded: Record<string, unknown> = { entity: { kind: entity.kind, id: entity.id } };
  if (Array.isArray(body.pointers)) forwarded.pointers = body.pointers.filter((p) => typeof p === 'string');
  if (typeof body.depth === 'number') forwarded.depth = body.depth;
  if (Array.isArray(body.provenance)) forwarded.provenance = body.provenance.filter((p) => typeof p === 'string');
  if (typeof body.version === 'string' && body.version) forwarded.version = body.version;
  return forwardGraphRequest(graphUrl(resolved.slug, 'blast-radius'), {
    method: 'POST',
    user: resolved.user,
    body: forwarded,
    unavailable: 'The blast-radius query is unavailable right now.',
  });
}
