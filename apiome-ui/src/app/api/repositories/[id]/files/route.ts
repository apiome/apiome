/**
 * Indexed repository files — proxies to GET /v1/tenants/{slug}/repositories/{id}/files
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const FORWARD_PARAMS = [
  'branch',
  'preset',
  'glob',
  'regex',
  'hide_non_importable',
  'skip_vendor',
  'include_hidden',
  'path_prefix',
  'limit',
  'offset',
] as const;

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await getAuthSession();
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

  const incoming = request.nextUrl.searchParams;
  const qs = new URLSearchParams();
  for (const key of FORWARD_PARAMS) {
    const v = incoming.get(key);
    if (v != null && v !== '') {
      qs.set(key, v);
    }
  }
  const q = qs.toString();
  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/repositories/${encodeURIComponent(id)}/files${q ? `?${q}` : ''}`;

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
    if (rest.ok && parsed && typeof parsed === 'object' && 'files' in parsed) {
      return NextResponse.json(parsed);
    }
    if (rest.status === 404) {
      return NextResponse.json({ success: false, error: 'Repository not found' }, { status: 404 });
    }
    const err =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `Repository files API error (${rest.status})`;
    return NextResponse.json({ success: false, error: err }, { status: rest.status >= 400 ? rest.status : 502 });
  } catch {
    return NextResponse.json(
      { success: false, error: 'Repository API unavailable (apiome-rest not reachable).' },
      { status: 503 }
    );
  }
}
