import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/export/projection-evidence — one bounded page of projection evidence
 * (EFP-2.1, #4813).
 *
 * Proxies REST `POST /v1/export/{tenant_slug}/projection-evidence`, which builds the
 * deterministic projection manifest for a `(source revision, target, options)` triple and
 * returns one cursor-paginated page of source→target outcome edges plus the nodes they
 * reference, together with the snapshot summary (`manifest_hash`, emitter/registry
 * versions, status/reason counts). The same inputs resolve to the same snapshot hash the
 * preview/verify envelopes embed, so the graph (EFP-2.2) and evidence drawer (EFP-2.3)
 * can page detail for exactly the snapshot the user previewed. Pass `redact_source: true`
 * to withhold source-native evidence values when relaying to viewers without source access.
 */
export async function POST(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return NextResponse.json(
        { success: false, error: 'Missing request body' },
        { status: 400 },
      );
    }

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      `/export/${ctx.tenantSlug}/projection-evidence`,
      body,
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    console.error('Error fetching projection evidence:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
