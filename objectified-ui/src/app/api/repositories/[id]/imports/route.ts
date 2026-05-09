/**
 * Recent catalog imports — proxies to GET /v1/tenants/{slug}/repositories/{id}/imports
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getServerSession(authOptions);
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const { id } = await params;
  if (!id || !UUID_RE.test(id)) {
    return NextResponse.json({ success: false, error: 'Invalid repository id' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug =
    tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  let limit = 100;
  const rawLimit = request.nextUrl.searchParams.get('limit');
  if (rawLimit != null && rawLimit !== '') {
    const n = parseInt(rawLimit, 10);
    if (!Number.isNaN(n)) limit = n;
  }
  const lim = Math.min(Math.max(limit, 1), 200);
  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/repositories/${encodeURIComponent(id)}/imports?limit=${lim}`;

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
    if (
      rest.ok &&
      parsed &&
      typeof parsed === 'object' &&
      'imports' in parsed &&
      'stats30d' in parsed &&
      Array.isArray((parsed as { imports: unknown }).imports)
    ) {
      return NextResponse.json({ ...(parsed as Record<string, unknown>), success: true });
    }
    if (rest.status === 404) {
      return NextResponse.json({ success: false, error: 'Repository not found' }, { status: 404 });
    }
    const err =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `Repository imports API error (${rest.status})`;
    return NextResponse.json({ success: false, error: err }, { status: rest.status >= 400 ? rest.status : 502 });
  } catch {
    return NextResponse.json(
      { success: false, error: 'Repository API unavailable (objectified-rest not reachable).' },
      { status: 503 }
    );
  }
}
