/**
 * `GET /tenant/{tenantSlug}/{projectSlug}/{versionSlug}/changes.json` — one version's stored
 * changelog, entries included (DBP-1.27, #7210).
 *
 * The version page renders the changelog's summary (status, severity, counts) with its one
 * statement and leaves the entries out unless it opens on the Changes tab. When a visitor opens
 * that tab afterwards, the page fetches the entries here. Same public gates as the page; the
 * private `error` column is never selected.
 *
 * Answers `200` with the row, `404` when the version is not public or does not exist, and `503`
 * with `Retry-After` when the catalog cannot be read.
 */

import { getPublicVersionChangelog } from '../../../../../../../lib/db/changelogs';
import { DatabaseUnavailableError, unavailableProblem } from '../../../../../../../lib/db/errors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ tenantSlug: string; projectSlug: string; versionSlug: string }> }
): Promise<Response> {
  const { tenantSlug, projectSlug, versionSlug } = await params;
  try {
    const row = await getPublicVersionChangelog(tenantSlug, projectSlug, versionSlug);
    if (!row) return Response.json({ detail: 'Unknown or unpublished API version.' }, { status: 404 });
    return Response.json(row, { headers: { 'Cache-Control': 'public, max-age=60' } });
  } catch (err) {
    if (err instanceof DatabaseUnavailableError) return unavailableProblem();
    throw err;
  }
}
