/**
 * Connector inventory row actions (CDG-1.6, #5957): link, ignore, unignore, import.
 *
 * Proxies `POST /v1/tenants/{slug}/connectors/{id}/items/{itemId}/{action}`. An unknown action is a
 * 404 here, before REST is asked.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  forwardConnectorRequest,
  isConnectorItemAction,
  resolveConnectorTenant,
  tenantUrl,
} from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; itemId: string; action: string }> }
) {
  const { id, itemId, action } = await params;
  if (!isConnectorItemAction(action)) {
    return NextResponse.json({ success: false, error: `Unknown action: ${action}.` }, { status: 404 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = action === 'link' || action === 'ignore' ? await request.json().catch(() => ({})) : undefined;
  const path = `connectors/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}/${action}`;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), { method: 'POST', user: resolved.user, body });
}
