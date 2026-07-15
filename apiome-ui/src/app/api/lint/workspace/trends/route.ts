/**
 * GET /api/lint/workspace/trends — daily remediation-vs-policy series (CLX-4.1, #4859).
 */
import { NextRequest } from 'next/server';
import { proxyToRest, requireSessionUser } from '../proxy';

export async function GET(request: NextRequest) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  const params = new URLSearchParams();
  const days = request.nextUrl.searchParams.get('days');
  const projectId = request.nextUrl.searchParams.get('projectId');
  if (days) params.set('days', days);
  if (projectId) params.set('projectId', projectId);
  const query = params.toString() ? `?${params.toString()}` : '';
  return proxyToRest(auth, `/lint/workspace/trends${query}`);
}
