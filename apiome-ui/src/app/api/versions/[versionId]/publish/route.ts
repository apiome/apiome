/**
 * API Proxy for Version Publish Operations
 *
 * Proxies requests to the REST API with JWT authentication.
 * Handles publish operations for specific versions.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import jwt from 'jsonwebtoken';
import { getTenantById } from '@lib/db/helper';
import { getJwtSigningSecret } from '@lib/rest-auth';

const REST_API_BASE_URL = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

/**
 * Helper to create authorization headers for REST API calls
 */
function createAuthHeaders(user: SessionUser): Record<string, string> {
  if (!user.user_id) {
    return { 'Content-Type': 'application/json' };
  }

  const secret = getJwtSigningSecret();
  if (!secret) {
    return { 'Content-Type': 'application/json' };
  }

  const encodedToken = jwt.sign(
    {
      user_id: user.user_id,
      sub: user.user_id,
      email: user.email,
      name: user.name,
      current_tenant_id: user.current_tenant_id,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '1h' }
  );

  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${encodedToken}`,
  };
}

/**
 * Read the sentence out of a FastAPI `detail`.
 *
 * The publish gates do not agree on the shape: the style-guide and documentation gates
 * refuse with a plain string, while the structured ones — the CTG-3.4 breaking-publish
 * guardrail, the ECA-3.1 verification policy, and the COL-2.3 approval gate — refuse with
 * `{message, <gate payload>}` so a client can render the verdict. Returning the object
 * verbatim put `[object Object]` in front of the reader, so the sentence is lifted out here
 * and the payload is left to whichever panel asks for it.
 *
 * @param detail Whatever the REST error body carried under `detail`.
 * @param defaultError The sentence to fall back to.
 * @returns A displayable sentence.
 */
function describeRestDetail(detail: unknown, defaultError: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return defaultError;
}

/**
 * Helper to handle REST API responses
 */
async function handleRestResponse(response: Response, defaultError: string): Promise<{ data: unknown; error: string | null; status: number }> {
  const contentType = response.headers.get('content-type');

  if (!contentType || !contentType.includes('application/json')) {
    const text = await response.text();
    return { data: null, error: text || defaultError, status: response.status || 500 };
  }

  const data = await response.json();

  if (!response.ok) {
    return {
      data: null,
      error: describeRestDetail(data.detail, defaultError),
      status: response.status,
    };
  }

  return { data, error: null, status: response.status };
}

/**
 * POST /api/versions/[versionId]/publish
 * Publish a version
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> }
) {
  try {
    const { versionId } = await params;
    const session = await getAuthSession();

    if (!session?.user) {
      return NextResponse.json(
        { success: false, error: 'Unauthorized' },
        { status: 401 }
      );
    }

    const user = session.user as { current_tenant_id?: string; user_id?: string };
    const tenantId = user.current_tenant_id;

    if (!tenantId) {
      return NextResponse.json(
        { success: false, error: 'No tenant selected' },
        { status: 400 }
      );
    }

    const tenant = await getTenantById(tenantId);
    if (!tenant || !tenant.slug) {
      return NextResponse.json(
        { success: false, error: 'Tenant not found' },
        { status: 404 }
      );
    }

    const tenantSlug = tenant.slug;
    const body = await request.json();
    const {
      projectId,
      visibility,
      shortMessage,
      changelog,
      changeReportBaselineMode,
      changeReportBaselineRevisionId,
      skipPublishChecks,
      forcePublishReason,
    } = body as {
      projectId?: string;
      visibility?: string;
      shortMessage?: string | null;
      changelog?: string | null;
      changeReportBaselineMode?: 'auto' | 'initial' | 'manual';
      changeReportBaselineRevisionId?: string | null;
      skipPublishChecks?: boolean;
      forcePublishReason?: string;
    };

    if (!projectId) {
      return NextResponse.json(
        { success: false, error: 'Project ID is required' },
        { status: 400 }
      );
    }

    const headers = createAuthHeaders({
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    });

    const payload: Record<string, unknown> = { visibility: visibility || 'private' };
    if (shortMessage !== undefined) payload.shortMessage = shortMessage;
    if (changelog !== undefined) payload.changelog = changelog;
    if (changeReportBaselineMode !== undefined) payload.changeReportBaselineMode = changeReportBaselineMode;
    if (changeReportBaselineRevisionId !== undefined) {
      payload.changeReportBaselineRevisionId = changeReportBaselineRevisionId;
    }
    if (skipPublishChecks) payload.skipPublishChecks = true;
    if (forcePublishReason !== undefined) payload.forcePublishReason = forcePublishReason;

    const response = await fetch(`${REST_API_BASE_URL}/versions/${tenantSlug}/${projectId}/${versionId}/publish`, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    const { data, error, status } = await handleRestResponse(response, 'Failed to publish version');

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, version: data });
  } catch (error) {
    console.error('Error publishing version:', error);
    const errorMessage = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json(
      { success: false, error: errorMessage },
      { status: 500 }
    );
  }
}
