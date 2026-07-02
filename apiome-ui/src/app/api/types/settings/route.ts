import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPut,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/types/settings — the tenant's type-registry settings (Settings UI #3472,
 * backed by REST #3472 `GET /v1/types/{tenant_slug}/settings`).
 *
 * Returns the saved settings, or the registry defaults (flagged `is_default: true`) when the
 * tenant has never saved any — so the Settings view always renders a complete configuration.
 */
export async function GET() {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { data, error, status } = await proxyRestGet(
      ctx.user,
      `/types/${encodeURIComponent(ctx.tenantSlug)}/settings`
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, settings: data });
  } catch (error) {
    console.error('Error fetching type-registry settings:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * PUT /api/types/settings — save the tenant's type-registry settings (#3472).
 *
 * Tenant-administrator only (enforced by the REST layer). The body may be a partial update;
 * omitted fields keep their current persisted value. The REST layer validates enum/range
 * values and returns the full persisted settings.
 */
export async function PUT(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json();

    const { data, error, status } = await proxyRestPut(
      ctx.user,
      `/types/${encodeURIComponent(ctx.tenantSlug)}/settings`,
      body
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, settings: data });
  } catch (error) {
    console.error('Error saving type-registry settings:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
