/**
 * The schema registry proxy — CDG-4.5 (#5977).
 *
 * Forwards `/api/schema-registry/<path>` to `/v1/tenants/{slug}/schema-registry/<path>` for the
 * catalog item's **Subjects** tab and the Workspace **Schema registry** page. Only the paths and
 * methods {@link registryProxyPath} allows are forwarded, and a write carries only its own fields
 * ({@link registryProxyBody}). Permissions (`imports:view` to read, `imports:edit` / `imports:delete`
 * to change) are REST's.
 *
 * `GET config` also returns the tenant slug and the Confluent-compatible base URL (`registryUrl`)
 * the serializer snippets point at.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { REST_API_BASE_URL } from '@lib/rest-auth';
import { registryBaseUrl, registryProxyBody, registryProxyPath, type RegistryProxyMethod } from '@lib/schema-registry';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The schema registry is unavailable (apiome-rest not reachable). Try again shortly.';

/** The route's dynamic segment. */
type Context = { params: Promise<{ path: string[] }> };

/**
 * Forward one allowed request.
 *
 * @param request - The browser's request.
 * @param context - The route params.
 * @param method - The HTTP method.
 * @returns REST's answer, or `404` for a path the proxy does not forward.
 */
async function forward(request: NextRequest, context: Context, method: RegistryProxyMethod): Promise<NextResponse> {
  const { path: segments } = await context.params;
  const path = registryProxyPath(segments ?? [], method);
  if (path === null) {
    return NextResponse.json({ success: false, error: 'Unknown schema registry path.' }, { status: 404 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body =
    method === 'PUT' || method === 'POST' ? registryProxyBody(path, await request.json().catch(() => ({}))) : undefined;
  const response = await forwardConnectorRequest(tenantUrl(resolved.slug, `schema-registry/${path}`), {
    method,
    user: resolved.user,
    body,
    unavailable: UNAVAILABLE,
  });
  if (path !== 'config' || !response.ok) return response;
  const config = (await response.json()) as Record<string, unknown>;
  return NextResponse.json({
    ...config,
    tenantSlug: resolved.slug,
    registryUrl: registryBaseUrl(REST_API_BASE_URL, resolved.slug),
  });
}

export async function GET(request: NextRequest, context: Context) {
  return forward(request, context, 'GET');
}

export async function PUT(request: NextRequest, context: Context) {
  return forward(request, context, 'PUT');
}

export async function POST(request: NextRequest, context: Context) {
  return forward(request, context, 'POST');
}

export async function DELETE(request: NextRequest, context: Context) {
  return forward(request, context, 'DELETE');
}
