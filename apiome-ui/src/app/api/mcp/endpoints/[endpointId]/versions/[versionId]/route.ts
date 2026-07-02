/**
 * MCP endpoint version detail — proxies to apiome-rest
 * GET /v1/mcp/{slug}/endpoints/{id}/versions/{versionId} (V2-MCP-23.1).
 *
 * Returns one version snapshot's full surface (tools / resources / prompts) plus its score and
 * grade — the data the browse detail view renders.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../../../auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ endpointId: string; versionId: string }> },
) {
  const session = await getServerSession(authOptions);
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const { endpointId, versionId } = await params;
  if (!endpointId || !UUID_RE.test(endpointId) || !versionId || !UUID_RE.test(versionId)) {
    return NextResponse.json({ success: false, error: 'Invalid endpoint or version id' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug =
    tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const url =
    `${REST_API_BASE_URL}/mcp/${encodeURIComponent(tenantSlug)}/endpoints/` +
    `${encodeURIComponent(endpointId)}/versions/${encodeURIComponent(versionId)}`;
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
    if (rest.ok && parsed && typeof parsed === 'object' && 'version' in parsed) {
      return NextResponse.json(parsed);
    }
    if (rest.status === 404) {
      return NextResponse.json({ success: false, error: 'MCP endpoint version not found' }, { status: 404 });
    }
    const err =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `MCP version API error (${rest.status})`;
    return NextResponse.json({ success: false, error: err }, { status: rest.status >= 400 ? rest.status : 502 });
  } catch {
    return NextResponse.json(
      { success: false, error: 'MCP version API unavailable (apiome-rest not reachable).' },
      { status: 503 },
    );
  }
}
