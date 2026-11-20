/**
 * API proxy for a catalog item's Arazzo workflows (COA-1.3, #7039).
 *
 * Proxies REST `GET /v1/workflows/{tenant_slug}/catalog/{item_id}` — the workflows persisted for
 * the item's latest revision, with each step's resolved operation and source-description status.
 */

import { proxyWorkflowsGet } from '../../_proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/workflows/catalog/[itemId].
 *
 * @param _request The incoming request (unused).
 * @param params Route params carrying the catalog item id.
 * @returns `{ success: true, workflows }`, or `{ success: false, error }` with the upstream status.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ itemId: string }> }) {
  const { itemId } = await params;
  return proxyWorkflowsGet(`catalog/${encodeURIComponent(itemId)}`, 'workflows', 'catalog item workflows');
}
