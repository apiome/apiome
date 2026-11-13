import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/** The filters the REST audit list accepts; anything else in the query string is dropped. */
const FORWARDED = ['action', 'actorId', 'projectId', 'versionId', 'since', 'until', 'limit', 'cursor'];

/**
 * GET /api/change-report-audit  (#2705)
 *
 * The tenant's change-report audit trail, newest first: report edits, regenerations,
 * submissions, approvals, rejections and PDF exports, and template changes. Tenant
 * administrators only (enforced by the REST layer). Filters: `action` (repeatable), `actorId`,
 * `projectId`, `versionId`, `since`, `until`, `limit`, `cursor`.
 */
export async function GET(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const incoming = new URL(request.url).searchParams;
    const query = new URLSearchParams();
    for (const name of FORWARDED) {
      for (const value of incoming.getAll(name)) {
        if (value) query.append(name, value);
      }
    }
    const suffix = query.toString() ? `?${query.toString()}` : '';

    const { data, error, status } = await proxyRestGet(
      ctx.user,
      `/tenants/${encodeURIComponent(ctx.tenantSlug)}/change-report-audit${suffix}`
    );
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }
    return NextResponse.json({ success: true, audit: data });
  } catch (error) {
    console.error('change-report audit:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
