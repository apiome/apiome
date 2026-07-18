/**
 * Tenant license proxy — OLO-5.5 (#4215).
 *
 * Forwards to apiome-rest `GET /v1/tenants/{slug}/license` (OLO-5.4) using the
 * session's current tenant slug. The upstream requires the caller to be a
 * member of the tenant holding `billing:view` (held by every built-in role),
 * so any signed-in member can read their tenant's plan, seat usage, and
 * effective feature entitlements.
 *
 * Errors keep the FastAPI `detail` payload intact (string or structured
 * `{code, message}` object) so the client can render stable OLO-5.3 license
 * error codes gracefully via `licenseErrors.describeLicenseError`.
 */

import { NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

export async function GET() {
  const session = await getServerSession(authOptions);
  const user = session?.user as
    | { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string }
    | undefined;

  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const tenant = await getTenantById(user.current_tenant_id);
  if (!tenant?.slug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 });
  }

  try {
    const response = await fetch(
      `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenant.slug)}/license`,
      {
        method: 'GET',
        headers: createRestAuthHeaders(user),
        cache: 'no-store',
      },
    );

    const contentType = response.headers.get('content-type');
    if (!contentType?.includes('application/json')) {
      const text = await response.text();
      return NextResponse.json(
        { success: false, error: text || 'Request failed' },
        { status: response.status >= 400 ? response.status : 502 },
      );
    }

    const data = await response.json();
    if (!response.ok) {
      // Pass `detail` through untouched — it may be a structured OLO-5.3
      // payload ({code, message}) the client maps to friendly guidance.
      return NextResponse.json(
        { success: false, error: data?.detail ?? 'Request failed' },
        { status: response.status },
      );
    }

    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
