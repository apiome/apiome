/**
 * Manual one-shot "Refresh Now" for a registered repository (RAR-5.2, #3533).
 *
 * Proxies to POST /v1/tenants/{slug}/repositories/{id}/refresh, which runs the
 * spec-faithful re-import path (RAR-4.1) for a single file or the whole
 * repository, honoring the freshness + divergence gates while bypassing the
 * auto-refresh cadence. The request body is optional:
 *   - omit both           → refresh every branch with a stored spec;
 *   - { branch }          → refresh that branch;
 *   - { path, branch? }   → refresh that single file.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
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

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
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

  // Body is optional; tolerate an empty body (whole-repo refresh).
  let body: unknown = {};
  try {
    const text = await request.text();
    if (text && text.trim()) body = JSON.parse(text);
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }
  const payload = body && typeof body === 'object' ? (body as Record<string, unknown>) : {};
  const forwarded: { path?: string; branch?: string } = {};
  if (typeof payload.path === 'string' && payload.path.trim()) forwarded.path = payload.path.trim();
  if (typeof payload.branch === 'string' && payload.branch.trim()) {
    forwarded.branch = payload.branch.trim();
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug =
    tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/repositories/${encodeURIComponent(id)}/refresh`;
  try {
    const rest = await fetch(url, {
      method: 'POST',
      headers: { ...createRestAuthHeaders(user), 'Content-Type': 'application/json' },
      body: JSON.stringify(forwarded),
      cache: 'no-store',
    });
    const text = await rest.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { raw: text };
    }
    if (rest.ok && parsed && typeof parsed === 'object' && 'enqueued' in parsed) {
      return NextResponse.json(parsed);
    }
    if (rest.status === 404) {
      return NextResponse.json({ success: false, error: 'Repository not found' }, { status: 404 });
    }
    const err =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `Repository API error (${rest.status})`;
    return NextResponse.json({ success: false, error: err }, { status: rest.status >= 400 ? rest.status : 502 });
  } catch {
    return NextResponse.json(
      { success: false, error: 'Repository API unavailable (apiome-rest not reachable).' },
      { status: 503 }
    );
  }
}
