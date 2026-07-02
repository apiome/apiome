/**
 * API proxy: Paths designer React Flow canvas (#2642).
 * GET/PUT → REST /v1/paths/{tenant}/{versionId}/{pathId}/canvas
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../../../auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

async function handleRestResponse(
  response: Response,
  defaultError: string
): Promise<{ data: unknown; error: string | null; status: number }> {
  const contentType = response.headers.get('content-type');

  if (!contentType || !contentType.includes('application/json')) {
    const text = await response.text();
    return { data: null, error: text || defaultError, status: response.status || 500 };
  }

  const data = await response.json();

  if (!response.ok) {
    return { data: null, error: data.detail || defaultError, status: response.status };
  }

  return { data, error: null, status: response.status };
}

/**
 * GET /api/paths/[versionId]/[pathId]/canvas
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ versionId: string; pathId: string }> }
) {
  try {
    const { versionId, pathId } = await params;
    const session = await getServerSession(authOptions);

    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }

    const user = session.user as { current_tenant_id?: string; user_id?: string };
    const tenantId = user.current_tenant_id;

    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }

    const tenant = await getTenantById(tenantId);
    if (!tenant || !tenant.slug) {
      return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 });
    }

    const headers = createRestAuthHeaders({
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    });

    const response = await fetch(
      `${REST_API_BASE_URL}/paths/${tenant.slug}/${versionId}/${pathId}/canvas`,
      { method: 'GET', headers }
    );

    const { data, error, status } = await handleRestResponse(response, 'Failed to load canvas');

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, canvas: data });
  } catch (error) {
    console.error('Error loading path canvas:', error);
    const errorMessage = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: errorMessage }, { status: 500 });
  }
}

/**
 * PUT /api/paths/[versionId]/[pathId]/canvas
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string; pathId: string }> }
) {
  try {
    const { versionId, pathId } = await params;
    const session = await getServerSession(authOptions);

    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }

    const user = session.user as { current_tenant_id?: string; user_id?: string };
    const tenantId = user.current_tenant_id;

    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }

    const tenant = await getTenantById(tenantId);
    if (!tenant || !tenant.slug) {
      return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 });
    }

    const body = await request.json();
    const headers = createRestAuthHeaders({
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    });

    const response = await fetch(
      `${REST_API_BASE_URL}/paths/${tenant.slug}/${versionId}/${pathId}/canvas`,
      {
        method: 'PUT',
        headers,
        body: JSON.stringify(body),
      }
    );

    const { data, error, status } = await handleRestResponse(response, 'Failed to save canvas');

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, canvas: data });
  } catch (error) {
    console.error('Error saving path canvas:', error);
    const errorMessage = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: errorMessage }, { status: 500 });
  }
}
