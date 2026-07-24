import { NextResponse } from 'next/server';
import { getAuthSession } from '@lib/auth/server-session';
import { getMigrationRuleTemplates } from '@lib/db/helper-database';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const session = await getAuthSession();
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const templates = await getMigrationRuleTemplates();
    return NextResponse.json({ success: true, templates });
  } catch (error) {
    console.error('Error fetching migration rule templates:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
