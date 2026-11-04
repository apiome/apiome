/**
 * `GET /tenant/{tenantSlug}/llms.txt` — the tenant's llms.txt over its published, public artifacts
 * (MFX-32.3, #4297). Built by the REST API; see `lib/agentic/siteManifest.ts`.
 */

import { serveSiteManifest, serverRestApiBaseUrl } from '../../../../../lib/agentic/siteManifest';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ tenantSlug: string }> }
): Promise<Response> {
  const { tenantSlug } = await params;
  return serveSiteManifest('llms.txt', tenantSlug, request.url, {
    restApiBaseUrl: serverRestApiBaseUrl(),
    basePath: process.env.NEXT_PUBLIC_BASE_PATH ?? '',
  });
}
