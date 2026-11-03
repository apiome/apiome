/**
 * Shared forwarding for the `/api/repositories/{id}/conflict-policy*` proxy routes
 * (RAR-4.5, #3531).
 *
 * Three handlers across two route files talk to the same REST surface with the same auth,
 * the same repository-id guard and the same error contract. The forwarding itself is the
 * repository-settings proxy ({@link forwardRepositorySettingsRequest}), which also serves the
 * per-branch refresh rules (RAR-6.4); this module fixes the conflict-policy path and envelope.
 */

import type { NextResponse } from 'next/server';
import {
  forwardRepositorySettingsRequest,
  readRepositorySettingsBody,
} from '@lib/repository-settings-proxy';

/**
 * Forward one conflict-policy request to REST and normalise its answer.
 *
 * REST nests its projection under `conflictPolicy`; the panel reads one flat object.
 *
 * @param repositoryId The repository id from the route params.
 * @param method HTTP method to forward (`GET` reads, `PUT` writes).
 * @param suffix Sub-path under `/conflict-policy` (`''` for the repository policy,
 *   `'/file'` for a per-file override).
 * @param body Payload for a write; omitted on a read.
 * @returns The response to hand back to the browser.
 */
export async function forwardConflictPolicyRequest(
  repositoryId: string,
  method: 'GET' | 'PUT',
  suffix: '' | '/file' = '',
  body?: unknown
): Promise<NextResponse> {
  return forwardRepositorySettingsRequest({
    repositoryId,
    method,
    subpath: `conflict-policy${suffix}`,
    envelope: 'conflictPolicy',
    body,
  });
}

/**
 * Read and parse a JSON request body.
 *
 * @param request The incoming request.
 * @returns The parsed body, or the 400 response for malformed JSON.
 */
export const readConflictPolicyBody = readRepositorySettingsBody;
