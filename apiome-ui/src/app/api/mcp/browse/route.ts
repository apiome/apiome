/**
 * Private MCP browse — proxies to apiome-rest GET /v1/mcp/{slug}/browse (V2-MCP-23.1).
 *
 * Returns the caller's cataloged MCP endpoints grouped by host (with capability counts, score
 * and last-discovered). When the REST service is unreachable, GET falls back to an empty browse
 * so the dashboard renders an empty state rather than erroring.
 */

import { NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

const EMPTY_BROWSE = { success: true, host_count: 0, endpoint_count: 0, groups: [] };

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
  const tenantSlug =
    tenant && typeof tenant === 'object' && 'slug' in tenant ? String((tenant as { slug: string }).slug) : '';
  if (!tenantSlug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 400 });
  }

  const url = `${REST_API_BASE_URL}/mcp/${encodeURIComponent(tenantSlug)}/browse`;
  try {
    const rest = await fetch(url, {
      method: 'GET',
      headers: createRestAuthHeaders(user),
      cache: 'no-store',
    });
    if (rest.ok) {
      const data = await rest.json().catch(() => null);
      if (data && typeof data === 'object' && 'groups' in data) {
        return NextResponse.json(data);
      }
    }
    return NextResponse.json(EMPTY_BROWSE);
  } catch {
    return NextResponse.json(EMPTY_BROWSE);
  }
}
