/**
 * Single MCP endpoint — proxies to objectified-rest:
 *   GET    /v1/mcp/{slug}/endpoints/{id}  (V2-MCP-23.1) — resolve an endpoint's version & identity.
 *   PATCH  /v1/mcp/{slug}/endpoints/{id}  (V2-MCP-24.2) — toggle mutable catalog state from the
 *          detail view: enable/disable and publish/unpublish.
 *   DELETE /v1/mcp/{slug}/endpoints/{id}  (V2-MCP-24.1) — discard an endpoint (e.g. a failed import
 *          whose auth/scan did not complete and that the user did not keep).
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
  proxyRestPatch,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

export async function GET(_request: NextRequest, { params }: { params: Promise<{ endpointId: string }> }) {
  const session = await getServerSession(authOptions);
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug =
    tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/mcp/${encodeURIComponent(tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}`;
  try {
    const rest = await fetch(url, {
      method: 'GET',
      headers: createRestAuthHeaders(user),
      cache: 'no-store',
    });
    const text = await rest.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { raw: text };
    }
    if (rest.ok && parsed && typeof parsed === 'object' && 'endpoint' in parsed) {
      return NextResponse.json(parsed);
    }
    if (rest.status === 404) {
      return NextResponse.json({ success: false, error: 'MCP endpoint not found' }, { status: 404 });
    }
    const err =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `MCP endpoint API error (${rest.status})`;
    return NextResponse.json({ success: false, error: err }, { status: rest.status >= 400 ? rest.status : 502 });
  } catch {
    return NextResponse.json(
      { success: false, error: 'MCP endpoint API unavailable (objectified-rest not reachable).' },
      { status: 503 },
    );
  }
}

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ endpointId: string }> }) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  // Only the detail view's toggles are forwarded; everything else is ignored so this proxy can
  // never patch fields it does not intend to (name, URL, transport, …).
  const body = (raw ?? {}) as Record<string, unknown>;
  const patch: Record<string, boolean> = {};
  if (typeof body.enabled === 'boolean') patch.enabled = body.enabled;
  if (typeof body.published === 'boolean') patch.published = body.published;
  if (Object.keys(patch).length === 0) {
    return NextResponse.json(
      { success: false, error: 'Provide at least one of: enabled, published (boolean).' },
      { status: 400 },
    );
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { data, error, status } = await proxyRestPatch(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}`,
    patch,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data ?? { success: true }, { status: status || 200 });
}

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ endpointId: string }> }) {
  const { endpointId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint id' }, { status: 400 });
  }

  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { data, error, status } = await proxyRestDelete(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/endpoints/${encodeURIComponent(endpointId)}`,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data ?? { success: true }, { status: status || 200 });
}
