/**
 * API proxy — version quality scoring.
 *
 *   GET  /api/version-quality/[versionId]?projectId=…
 *     → latest persisted snapshot for the version, or `null` if never computed.
 *   POST /api/version-quality/[versionId]?projectId=…
 *     → kicks off a fresh on-demand run; returns `{ snapshot, previous }`.
 *
 * Mirrors the auth + tenant-slug resolution pattern the rest of the dashboard
 * proxies use: tenant comes from the session, projectId comes from the
 * caller, the REST tier sees a tenant-slug-prefixed path. The POST has no
 * request body — the run is parameter-less; we still allow callers to pass a
 * body without rejecting it.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import jwt from 'jsonwebtoken';
import { authOptions } from '../../auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';

const REST_API_BASE_URL =
  process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

function createAuthHeaders(user: SessionUser): Record<string, string> {
  const secret = process.env.NEXTAUTH_SECRET;
  if (!user.user_id || !secret) {
    return { 'Content-Type': 'application/json' };
  }
  const token = jwt.sign(
    {
      user_id: user.user_id,
      sub: user.user_id,
      email: user.email,
      name: user.name,
      current_tenant_id: user.current_tenant_id,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '1h' },
  );
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  };
}

async function readJson(response: Response): Promise<unknown> {
  const ct = response.headers.get('content-type') ?? '';
  if (!ct.includes('application/json')) {
    const text = await response.text();
    return text ? { detail: text } : null;
  }
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

interface ResolvedContext {
  tenantSlug: string;
  projectId: string;
  headers: Record<string, string>;
}

async function resolveContext(
  request: NextRequest,
): Promise<{ ctx: ResolvedContext; error?: never } | { ctx?: never; error: NextResponse }> {
  const session = await getServerSession(authOptions);
  if (!session?.user) {
    return {
      error: NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 }),
    };
  }

  const user = session.user as { current_tenant_id?: string; user_id?: string };
  const tenantId = user.current_tenant_id;
  if (!tenantId) {
    return {
      error: NextResponse.json(
        { success: false, error: 'No tenant selected' },
        { status: 400 },
      ),
    };
  }

  const projectId = new URL(request.url).searchParams.get('projectId');
  if (!projectId) {
    return {
      error: NextResponse.json(
        { success: false, error: 'Project ID is required' },
        { status: 400 },
      ),
    };
  }

  const tenant = await getTenantById(tenantId);
  if (!tenant?.slug) {
    return {
      error: NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 }),
    };
  }

  return {
    ctx: {
      tenantSlug: tenant.slug,
      projectId,
      headers: createAuthHeaders({
        user_id: user.user_id,
        email: session.user.email,
        name: session.user.name,
        current_tenant_id: tenantId,
      }),
    },
  };
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> },
) {
  try {
    const { versionId } = await params;
    const resolved = await resolveContext(request);
    if (resolved.error) return resolved.error;
    const { tenantSlug, projectId, headers } = resolved.ctx;

    const url = `${REST_API_BASE_URL}/version-quality/${tenantSlug}/${projectId}/${versionId}`;
    const response = await fetch(url, { method: 'GET', headers });
    const body = await readJson(response);

    if (!response.ok) {
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? (body as { detail?: unknown }).detail
          : null;
      return NextResponse.json(
        { success: false, error: typeof detail === 'string' ? detail : 'Failed to load quality snapshot' },
        { status: response.status },
      );
    }

    /* The REST endpoint returns JSON `null` when the version has never been
       scored — surface that as `snapshot: null` so the UI can render its
       compute-quality CTA without checking for a separate sentinel. */
    return NextResponse.json({ success: true, snapshot: body ?? null });
  } catch (error) {
    console.error('Error fetching version quality snapshot:', error);
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : 'Internal server error',
      },
      { status: 500 },
    );
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> },
) {
  try {
    const { versionId } = await params;
    const resolved = await resolveContext(request);
    if (resolved.error) return resolved.error;
    const { tenantSlug, projectId, headers } = resolved.ctx;

    const url = `${REST_API_BASE_URL}/version-quality/${tenantSlug}/${projectId}/${versionId}/run`;
    const response = await fetch(url, { method: 'POST', headers });
    const body = await readJson(response);

    if (!response.ok) {
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? (body as { detail?: unknown }).detail
          : null;
      return NextResponse.json(
        { success: false, error: typeof detail === 'string' ? detail : 'Failed to run quality scoring' },
        { status: response.status },
      );
    }

    const payload = (body ?? {}) as { snapshot?: unknown; previous?: unknown };
    return NextResponse.json({
      success: true,
      snapshot: payload.snapshot ?? null,
      previous: payload.previous ?? null,
    });
  } catch (error) {
    console.error('Error running version quality:', error);
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : 'Internal server error',
      },
      { status: 500 },
    );
  }
}
