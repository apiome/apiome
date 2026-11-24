/**
 * `GET /api/search/hit-versions?…` — every published version of one search hit's project, for the
 * hit's version menu (DBP-1.27, #7210).
 *
 * The results page fills each menu with the project's newest versions (`HIT_VERSIONS_CAP`). When a
 * project has more, the menu offers **Show all versions** and asks here. Parameters name the hit as
 * the page has it: `id` (hit id), `type` (`version`, `operation` or `schema`), `tenant`, `project`,
 * `version` (the hit's own version), and for an operation `method` and `path`, for a schema `name`.
 *
 * Public and read-only; the statement applies the same public gates as search. Answers `200` with
 * `{ versions }` (empty when the hit is not eligible or its project is not public), `400` for a
 * malformed request, and `503` with `Retry-After` when the catalog cannot be read.
 */

import { runAllHitVersions } from '../../../../../lib/db/search';
import { DatabaseUnavailableError, unavailableProblem } from '../../../../../lib/db/errors';
import { COMPARE_KINDS } from '../../../../../lib/search/compare';
import type { CatalogSearchHit } from '../../../../../lib/search/hits';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Longest value any parameter may have. */
const MAX_PARAM_LENGTH = 512;

export async function GET(request: Request): Promise<Response> {
  const params = new URL(request.url).searchParams;
  const read = (name: string): string | null => {
    const value = params.get(name)?.trim();
    return value && value.length <= MAX_PARAM_LENGTH ? value : null;
  };
  const [id, type, tenant, project, version] = [
    read('id'),
    read('type'),
    read('tenant'),
    read('project'),
    read('version'),
  ];
  if (!id || !tenant || !project || !version || !type || !(COMPARE_KINDS as readonly string[]).includes(type)) {
    return Response.json({ detail: 'The request does not name a version, operation or schema hit.' }, { status: 400 });
  }

  const hit = {
    hit_id: id,
    hit_type: type,
    tenant_slug: tenant,
    project_slug: project,
    version_slug: version,
    method: read('method'),
    path: read('path'),
    anchor_key: read('name'),
  } as CatalogSearchHit;

  try {
    const versions = await runAllHitVersions(hit);
    return Response.json({ versions }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (err) {
    if (err instanceof DatabaseUnavailableError) return unavailableProblem();
    throw err;
  }
}
