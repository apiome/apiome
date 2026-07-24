/**
 * Tenant repositories — proxies to apiome-rest GET/POST /v1/tenants/{slug}/repositories.
 * When the REST service is unreachable or returns 404 for this path, GET falls back to [] and POST returns 501.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

async function restGetRepositories(tenantSlug: string, user: SessionUser): Promise<Response | null> {
  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/repositories`;
  try {
    return await fetch(url, {
      method: 'GET',
      headers: createRestAuthHeaders(user),
      cache: 'no-store',
    });
  } catch {
    return null;
  }
}

export async function GET() {
  const session = await getAuthSession();
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug = tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const rest = await restGetRepositories(tenantSlug, user);
  if (rest?.ok) {
    const data = await rest.json().catch(() => null);
    if (data && typeof data === 'object' && 'repositories' in data) {
      return NextResponse.json(data);
    }
    if (Array.isArray(data)) {
      return NextResponse.json({ success: true, repositories: data });
    }
  }

  return NextResponse.json({ success: true, repositories: [] });
}

export async function POST(request: NextRequest) {
  const session = await getAuthSession();
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    body = null;
  }
  if (!body || typeof body !== 'object') {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug = tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/repositories`;
  try {
    const rest = await fetch(url, {
      method: 'POST',
      headers: createRestAuthHeaders(user),
      body: JSON.stringify(body),
    });
    if (rest.status !== 404) {
      const text = await rest.text();
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = { raw: text };
      }
      return NextResponse.json(parsed, { status: rest.status });
    }
  } catch {
    /* fall through */
  }

  return NextResponse.json(
    {
      success: false,
      error:
        'Repository API unavailable (apiome-rest not reachable or POST /v1/tenants/{slug}/repositories returned 404). Ensure the API is running and migration 20260430-210000.sql has been applied.',
    },
    { status: 501 }
  );
}
