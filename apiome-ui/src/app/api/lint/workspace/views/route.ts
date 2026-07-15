/**
 * GET  /api/lint/workspace/views — list the caller's saved workspace views (CLX-4.1, #4859).
 * POST /api/lint/workspace/views — save the current filter bundle under a name.
 */
import { NextRequest, NextResponse } from 'next/server';
import { proxyToRest, requireSessionUser } from '../proxy';

export async function GET() {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  return proxyToRest(auth, '/lint/workspace/views');
}

export async function POST(request: NextRequest) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }
  return proxyToRest(auth, '/lint/workspace/views', { method: 'POST', body });
}
