/**
 * Recent catalog imports from a registered repository (Postgres-backed metrics).
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import {
  listTenantRepositoryImports,
  tenantRepositoryBelongsToTenant,
  tenantRepositoryImportStats30d,
} from '@lib/db/repository-import-metrics';

export const dynamic = 'force-dynamic';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface SessionUser {
  user_id?: string;
  current_tenant_id?: string;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await getAuthSession();
  const user = session?.user as SessionUser | undefined;
  if (!user?.user_id) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  if (!user.current_tenant_id) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }

  const { id } = await params;
  if (!id || !UUID_RE.test(id)) {
    return NextResponse.json({ success: false, error: 'Invalid repository id' }, { status: 400 });
  }

  const tenantId = user.current_tenant_id;
  const ok = await tenantRepositoryBelongsToTenant(tenantId, id);
  if (!ok) {
    return NextResponse.json({ success: false, error: 'Repository not found' }, { status: 404 });
  }

  let limit = 100;
  const rawLimit = request.nextUrl.searchParams.get('limit');
  if (rawLimit != null && rawLimit !== '') {
    const n = parseInt(rawLimit, 10);
    if (!Number.isNaN(n)) limit = n;
  }

  try {
    const [imports, stats30d] = await Promise.all([
      listTenantRepositoryImports({ tenantId, repositoryId: id, limit }),
      tenantRepositoryImportStats30d(tenantId, id),
    ]);
    return NextResponse.json({ success: true, imports, stats30d });
  } catch (e) {
    console.error('[repositories/imports]', e);
    return NextResponse.json(
      { success: false, error: e instanceof Error ? e.message : 'Failed to load import metrics' },
      { status: 500 }
    );
  }
}
