/**
 * `GET|POST /api/portal/feedback/{tenant}/{project}/{version}/threads` — the reader's feedback
 * threads on a version (list, open). COL-4.4 (#4528); see `../../../../proxy.ts`.
 */

import type { NextRequest, NextResponse } from 'next/server';

import { forwardFeedback } from '../../../../proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ tenant: string; project: string; version: string }> };

export async function GET(request: NextRequest, { params }: Params): Promise<NextResponse> {
  return forwardFeedback(request, await params, 'GET');
}

export async function POST(request: NextRequest, { params }: Params): Promise<NextResponse> {
  return forwardFeedback(request, await params, 'POST');
}
