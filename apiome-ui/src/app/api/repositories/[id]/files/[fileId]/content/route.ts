/**
 * Repository file body — proxies to
 * GET /v1/tenants/{slug}/repositories/{id}/files/{fileId}/content
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

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const session = await getAuthSession();
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const { id, fileId } = await params;
  if (!id || !UUID_RE.test(id) || !fileId || !UUID_RE.test(fileId)) {
    return NextResponse.json({ success: false, error: 'Invalid repository or file id' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  const tenantSlug =
    tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}/repositories/${encodeURIComponent(id)}/files/${encodeURIComponent(fileId)}/content`;

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
    if (rest.ok && parsed && typeof parsed === 'object' && 'content' in parsed && 'path' in parsed) {
      return NextResponse.json(parsed);
    }
    if (rest.status === 404) {
      return NextResponse.json({ success: false, error: 'File not found' }, { status: 404 });
    }
    if (rest.status === 413) {
      const detail =
        parsed && typeof parsed === 'object' && 'detail' in parsed
          ? String((parsed as { detail: unknown }).detail)
          : 'File too large';
      return NextResponse.json({ success: false, error: detail }, { status: 413 });
    }
    if (rest.status === 501) {
      const detail =
        parsed && typeof parsed === 'object' && 'detail' in parsed
          ? String((parsed as { detail: unknown }).detail)
          : 'Not implemented for this provider';
      return NextResponse.json({ success: false, error: detail }, { status: 501 });
    }
    const err =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : `Repository file API error (${rest.status})`;
    return NextResponse.json({ success: false, error: err }, { status: rest.status >= 400 ? rest.status : 502 });
  } catch {
    return NextResponse.json(
      { success: false, error: 'Repository API unavailable (apiome-rest not reachable).' },
      { status: 503 }
    );
  }
}
