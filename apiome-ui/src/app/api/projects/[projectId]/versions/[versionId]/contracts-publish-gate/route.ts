/**
 * GET /api/projects/[projectId]/versions/[versionId]/contracts-publish-gate
 * Proxies to REST GET /v1/versions/{tenantSlug}/{projectId}/{versionId}/contracts-publish-gate
 *
 * Preflights the PFX-7.3 (#6963) contracts gate for the publish dialog: whether the Pact
 * can-i-deploy verdict for this revision says it breaks a contract, and whether the tenant's
 * `contracts.publishPolicy` warns or blocks. Read-only — nothing is published or stored. The
 * `versions:view` and `pacts:view` permissions are REST's.
 */
import { NextRequest, NextResponse } from 'next/server';
import { REST_API_BASE_URL } from '@lib/rest-auth';
import { forwardConnectorRequest, resolveConnectorTenant } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

/** A project or revision id: a UUID, as every catalog row uses. */
const ID = /^[0-9a-fA-F-]{36}$/;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string; versionId: string }> }
) {
  const { projectId, versionId } = await params;
  if (!ID.test(projectId) || !ID.test(versionId)) {
    return NextResponse.json({ success: false, error: 'Invalid project or version id' }, { status: 400 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(
    `${REST_API_BASE_URL}/versions/${encodeURIComponent(resolved.slug)}/${projectId}/${versionId}/contracts-publish-gate`,
    { method: 'GET', user: resolved.user }
  );
}
