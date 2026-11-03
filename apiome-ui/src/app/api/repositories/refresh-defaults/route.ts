/**
 * Workspace refresh defaults for repositories (RAR-6.5, #3542) — proxies to
 * `GET/PUT /v1/tenants/{slug}/repository-refresh-defaults`.
 *
 * The defaults are the cadence, conflict policy and auto-refresh switch a new repository starts
 * from; a `PUT` can re-apply them to the repository settings that follow them. Anyone who can
 * view imports reads them; only a workspace administrator writes them (REST answers 403).
 *
 * `refresh-defaults` is a static sibling of `[id]` under `/api/repositories`, and Next.js matches
 * static segments ahead of dynamic ones, so it never collides with `/api/repositories/{uuid}`.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  forwardWorkspaceSettingsRequest,
  readRepositorySettingsBody,
} from '@lib/repository-settings-proxy';

export const dynamic = 'force-dynamic';

const PATH = 'repository-refresh-defaults';
const ENVELOPE = 'refreshDefaults';

/**
 * Read the workspace's refresh defaults and how many repositories follow them.
 *
 * @returns The flattened refresh-defaults projection.
 */
export async function GET(): Promise<NextResponse> {
  return forwardWorkspaceSettingsRequest({ method: 'GET', path: PATH, envelope: ENVELOPE });
}

/**
 * Set the workspace's refresh defaults.
 *
 * @param request Carries `{ refreshIntervalSeconds, conflictPolicy, autoRefreshEnabled, applyToInheriting }`.
 * @returns The projection after the update.
 */
export async function PUT(request: NextRequest): Promise<NextResponse> {
  const parsed = await readRepositorySettingsBody(request);
  if ('error' in parsed) return parsed.error;
  return forwardWorkspaceSettingsRequest({ method: 'PUT', path: PATH, envelope: ENVELOPE, body: parsed.body });
}
