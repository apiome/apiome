/**
 * POST /api/lint/workspace/decisions/bulk — bulk finding decision actions (CLX-4.1, #4859).
 * Authorized (lint_findings RBAC), audited (decision events), reversible (beforeState).
 */
import { NextRequest, NextResponse } from 'next/server';
import { proxyToRest, requireSessionUser } from '../../proxy';

export async function POST(request: NextRequest) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }
  return proxyToRest(auth.user, '/lint/workspace/decisions/bulk', { method: 'POST', body });
}
