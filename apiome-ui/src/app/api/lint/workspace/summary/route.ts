/**
 * GET /api/lint/workspace/summary — tenant lint posture rollup (CLX-4.1, #4859).
 */
import { NextRequest } from 'next/server';
import { proxyToRest, requireSessionUser } from '../proxy';

export async function GET(request: NextRequest) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  const projectId = request.nextUrl.searchParams.get('projectId');
  const query = projectId ? `?projectId=${encodeURIComponent(projectId)}` : '';
  return proxyToRest(auth.user, `/lint/workspace/summary${query}`);
}
