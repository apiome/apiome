import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/primitives/health — registry storage status (#3450), surfaced by the Settings UI
 * #3472 "Registry storage" section.
 *
 * Proxies the anonymous REST registry probe `GET /v1/primitives/health`, which reports whether
 * the shared `apiome-db` connection backing `apiome.primitives` is reachable. There is no
 * separate registry database (single-DB design, §1a), so this reflects the application DB's
 * registry layer rather than a distinct store.
 */
export async function GET() {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { data, error, status } = await proxyRestGet(ctx.user, `/primitives/health`);

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, health: data });
  } catch (error) {
    console.error('Error fetching registry health:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
