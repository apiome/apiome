/**
 * `POST /api/portal/feedback/{tenant}/{project}/{version}/threads/{threadId}/{comments|resolve|reopen}`
 * — reply in, resolve, or reopen one of the reader's feedback threads. COL-4.4 (#4528); see
 * `../../../../../../proxy.ts`.
 */

import { NextResponse, type NextRequest } from 'next/server';

import { isFeedbackAction } from '../../../../../../../../../../../lib/portal/feedback';
import { forwardFeedback } from '../../../../../../proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

type Params = {
  params: Promise<{ tenant: string; project: string; version: string; threadId: string; action: string }>;
};

export async function POST(request: NextRequest, { params }: Params): Promise<NextResponse> {
  const { action, ...route } = await params;
  if (!isFeedbackAction(action)) {
    return NextResponse.json({ detail: { code: 'feedback-not-found', message: 'Not found.' } }, { status: 404 });
  }
  return forwardFeedback(request, { ...route, action }, 'POST');
}
