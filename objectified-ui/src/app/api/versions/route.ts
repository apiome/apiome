/**
 * API Proxy for Versions Management
 *
 * Proxies requests to the REST API with JWT authentication from NextAuth session.
 * This ensures the UI application uses the REST API for all version operations.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import jwt from 'jsonwebtoken';
import { authOptions } from '../auth/[...nextauth]/route';
import { getTenantById } from '@lib/db/helper';

const REST_API_BASE_URL = process.env.NEXT_PUBLIC_REST_API_BASE_URL || 'http://localhost:8000/v1';

interface SessionUser {
  user_id?: string;
  email?: string | null;
  name?: string | null;
  current_tenant_id?: string;
}

/**
 * Helper to create authorization headers for REST API calls
 * Creates a JWT token from the session for authentication
 */
function createAuthHeaders(user: SessionUser): Record<string, string> {
  console.log('[versions] createAuthHeaders called with:', {
    user_id: user.user_id,
    email: user.email,
    current_tenant_id: user.current_tenant_id,
  });

  if (!user.user_id) {
    console.error('[versions] No user_id in session');
    return { 'Content-Type': 'application/json' };
  }

  const secret = process.env.NEXTAUTH_SECRET;
  if (!secret) {
    console.error('[versions] NEXTAUTH_SECRET not configured');
    return { 'Content-Type': 'application/json' };
  }

  // Create a JWT token with user info for the REST API
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

  console.log('[versions] JWT created successfully for user:', user.user_id);

  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${encodedToken}`,
  };
}

/**
 * Helper to handle REST API responses
 */
async function handleRestResponse(response: Response, defaultError: string): Promise<{ data: unknown; error: string | null; status: number }> {
  const contentType = response.headers.get('content-type');

  if (!contentType || !contentType.includes('application/json')) {
    const text = await response.text();
    console.error('Non-JSON response from REST API:', text);
    return { data: null, error: text || defaultError, status: response.status || 500 };
  }

  const data = await response.json();

  if (!response.ok) {
    const detail = data.detail;
    const errMsg =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail && typeof (detail as { message?: unknown }).message === 'string'
          ? (detail as { message: string }).message
          : defaultError;
    return { data: null, error: errMsg, status: response.status };
  }

  return { data, error: null, status: response.status };
}

/**
 * GET /api/versions?projectId=xxx
 * List all versions for a project
 */
export async function GET(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);

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

    // Get project ID from query params
    const { searchParams } = new URL(request.url);
    const projectId = searchParams.get('projectId');
    const lifecycle = searchParams.get('lifecycle');

    if (!projectId) {
      return NextResponse.json(
        { success: false, error: 'Project ID is required' },
        { status: 400 }
      );
    }

    // Get tenant slug
    const tenant = await getTenantById(tenantId);
    if (!tenant || !tenant.slug) {
      return NextResponse.json(
        { success: false, error: 'Tenant not found' },
        { status: 404 }
      );
    }

    const tenantSlug = tenant.slug;

    // Build REST API URL
    const qs = lifecycle ? `?lifecycle=${encodeURIComponent(lifecycle)}` : '';
    const url = `${REST_API_BASE_URL}/versions/${tenantSlug}/${projectId}${qs}`;

    // Create auth headers with JWT token from session
    const headers = createAuthHeaders({
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    });

    // Forward request to REST API
    const response = await fetch(url, {
      method: 'GET',
      headers,
    });

    const { data, error, status } = await handleRestResponse(response, 'Failed to fetch versions');

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, versions: data });
  } catch (error) {
    console.error('Error fetching versions:', error);
    const errorMessage = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json(
      { success: false, error: errorMessage },
      { status: 500 }
    );
  }
}

/**
 * POST /api/versions
 * Create a new version
 */
export async function POST(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);

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

    // Get tenant slug
    const tenant = await getTenantById(tenantId);
    if (!tenant || !tenant.slug) {
      return NextResponse.json(
        { success: false, error: 'Tenant not found' },
        { status: 404 }
      );
    }

    const tenantSlug = tenant.slug;

    // Get request body
    const body = await request.json();
    const { projectId, ...versionData } = body;

    if (!projectId) {
      return NextResponse.json(
        { success: false, error: 'Project ID is required' },
        { status: 400 }
      );
    }

    // Create auth headers with JWT token from session
    const headers = createAuthHeaders({
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    });

    // Forward request to REST API
    const response = await fetch(`${REST_API_BASE_URL}/versions/${tenantSlug}/${projectId}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(versionData),
    });

    const { data, error, status } = await handleRestResponse(response, 'Failed to create version');

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, version: data });
  } catch (error) {
    console.error('Error creating version:', error);
    const errorMessage = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json(
      { success: false, error: errorMessage },
      { status: 500 }
    );
  }
}
