/**
 * API proxy for the operation an Arazzo step calls (COA-1.3, #7039).
 *
 * Proxies REST `GET /v1/workflows/{tenant_slug}/operations/{path_operation_id}` — the step
 * drawer's operation: method, route, summary, owning project, parameters and responses.
 */

import { proxyWorkflowsGet } from '../../_proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/workflows/operations/[operationId].
 *
 * @param _request The incoming request (unused).
 * @param params Route params carrying the `path_operation.id`.
 * @returns `{ success: true, operation }`, or `{ success: false, error }` with the upstream status.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ operationId: string }> }) {
  const { operationId } = await params;
  return proxyWorkflowsGet(`operations/${encodeURIComponent(operationId)}`, 'operation', 'workflow step operation');
}
