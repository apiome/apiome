/**
 * API proxy for a revision's Arazzo workflows (COA-1.3, #7039).
 *
 * Proxies REST `GET /v1/workflows/{tenant_slug}/versions/{version_id}` — used by the project
 * Versions page's **Workflows** tab.
 */

import { proxyWorkflowsGet } from '../../_proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/workflows/versions/[versionId].
 *
 * @param _request The incoming request (unused).
 * @param params Route params carrying the revision (`versions.id`).
 * @returns `{ success: true, workflows }`, or `{ success: false, error }` with the upstream status.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ versionId: string }> }) {
  const { versionId } = await params;
  return proxyWorkflowsGet(`versions/${encodeURIComponent(versionId)}`, 'workflows', 'revision workflows');
}
