/**
 * PATCH  /api/lint/workspace/views/{viewId} — update a saved workspace view (CLX-4.1, #4859).
 * DELETE /api/lint/workspace/views/{viewId} — delete a saved workspace view.
 */
import { NextRequest, NextResponse } from 'next/server';
import { proxyToRest, requireSessionUser } from '../../proxy';

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ viewId: string }> },
) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  const { viewId } = await params;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }
  return proxyToRest(auth, `/lint/workspace/views/${encodeURIComponent(viewId)}`, {
    method: 'PATCH',
    body,
  });
}

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ viewId: string }> },
) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  const { viewId } = await params;
  return proxyToRest(auth, `/lint/workspace/views/${encodeURIComponent(viewId)}`, {
    method: 'DELETE',
  });
}
