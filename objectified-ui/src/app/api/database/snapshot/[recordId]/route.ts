import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { getClassSchemaById, updateDataRecord, updateDataSnapshotEmbedding, deleteDataRecord } from '@lib/db/helper-database';
import { validatePayloadAgainstSchema } from '@lib/database/validateSchema';
import { embedRecordData, EMBEDDING_MODEL } from '@lib/embedding';

export const dynamic = 'force-dynamic';

export async function PATCH(
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
    const userId = (session.user as { user_id?: string }).user_id ?? null;

    const { recordId } = await params;
    if (!recordId) {
      return NextResponse.json({ success: false, error: 'recordId required' }, { status: 400 });
    }

    let body: { classSchemaId?: string; data?: Record<string, unknown> };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
    }
    const { classSchemaId, data } = body;
    if (!classSchemaId || typeof classSchemaId !== 'string') {
      return NextResponse.json({ success: false, error: 'classSchemaId required' }, { status: 400 });
    }
    if (data === undefined || typeof data !== 'object' || data === null) {
      return NextResponse.json({ success: false, error: 'data must be an object' }, { status: 400 });
    }

    const row = await getClassSchemaById(classSchemaId, tenantId);
    if (!row) {
      return NextResponse.json({ success: false, error: 'Class schema not found' }, { status: 404 });
    }

    const validation = validatePayloadAgainstSchema(data, row.schema);
    if (!validation.valid) {
      return NextResponse.json(
        { success: false, error: 'Validation failed', errors: validation.errors },
        { status: 400 }
      );
    }

    await updateDataRecord(recordId, classSchemaId, tenantId, data, userId);

    // Automatic vectorization on update (best-effort, non-blocking)
    embedRecordData(data)
      .then((embedding) => {
        if (embedding) return updateDataSnapshotEmbedding(recordId, embedding, EMBEDDING_MODEL);
      })
      .catch((err) => console.error('[snapshot/update] Vectorization failed:', err));

    return NextResponse.json({ success: true, record_id: recordId });
  } catch (error) {
    console.error('Error updating record:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

export async function DELETE(
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
    const userId = (session.user as { user_id?: string }).user_id ?? null;

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

    await deleteDataRecord(recordId, classSchemaId, tenantId, userId);
    return NextResponse.json({ success: true, record_id: recordId });
  } catch (error) {
    console.error('Error deleting record:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
