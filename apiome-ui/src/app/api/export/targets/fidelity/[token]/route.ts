import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';
import { restErrorCode } from '@lib/rest-error-message';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/targets/fidelity/{token} — poll a deferred targets list for its fidelity badges.
 *
 * Proxies REST `GET /v1/export/{tenant_slug}/targets/fidelity/{token}`: `{ status, targets, error }`,
 * where `status` is `pending` while the source is being scored, `ready` with the scored `targets`
 * (the same entries `GET /api/export/targets` returns), or `failed` with an `error`. A 404 with code
 * `fidelity-job-unknown` means the job expired or another REST worker ran it: request the targets
 * list again.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ token: string }> }) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { token } = await params;
    const { data, error, status, detail } = await proxyRestGet(
      ctx.user,
      `/export/${encodeURIComponent(ctx.tenantSlug)}/targets/fidelity/${encodeURIComponent(token)}`,
    );

    if (error) {
      return NextResponse.json({ success: false, error, code: restErrorCode(detail) }, { status });
    }

    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    console.error('Error polling export target fidelity:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
