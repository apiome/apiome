import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getClassSchemaById, getRecordHistory } from '@lib/db/helper-database';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ recordId: string }> }
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = (session.user as { current_tenant_id?: string }).current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }

    const { recordId } = await params;
    if (!recordId) {
      return NextResponse.json({ success: false, error: 'recordId required' }, { status: 400 });
    }

    const { searchParams } = new URL(request.url);
    const classSchemaId = searchParams.get('classSchemaId');
    if (!classSchemaId) {
      return NextResponse.json({ success: false, error: 'classSchemaId query parameter required' }, { status: 400 });
    }

    const row = await getClassSchemaById(classSchemaId, tenantId);
    if (!row) {
      return NextResponse.json({ success: false, error: 'Class schema not found' }, { status: 404 });
    }

    const events = await getRecordHistory(recordId, classSchemaId, tenantId);
    return NextResponse.json({ success: true, events });
  } catch (error) {
    console.error('Error fetching record history:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
