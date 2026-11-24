/**
 * The request handling shared by the two changelog feed routes (DBP-1.27, #7210).
 *
 * `changelog.xml` and `changelog.json` differ only in how they render. Both:
 *
 *   1. read the feed's validator — one small aggregate, no changelog payload;
 *   2. answer `304` when the request's `If-None-Match` carries the ETag derived from it;
 *   3. otherwise read the rows and render.
 *
 * So a polling reader whose feed has not changed costs one small query, where it used to cost the
 * project lookup with its card facts, 50 full changelog payloads and a render to hash.
 */

import { getFeedRows, getFeedValidator } from '../db/changelogs';
import { DatabaseUnavailableError, unavailableResponse } from '../db/errors';
import type { PublicVersionChangelogRow } from '../changelog/types';
import {
  buildProjectFeedMeta,
  feedUpdatedFromRows,
  feedValidatorETag,
  ifNoneMatchMatches,
  type ChangelogFeedMeta,
} from './changelog-feed';

/** One feed format. */
export interface FeedFormat {
  /** The route's extension. */
  extension: 'xml' | 'json';
  /** The response's `Content-Type`. */
  contentType: string;
  /** Render the feed body. */
  render: (meta: ChangelogFeedMeta, rows: PublicVersionChangelogRow[]) => string;
}

/**
 * Answer a changelog feed request.
 *
 * @param request - The request (its URL gives the feed's origin; `If-None-Match` is honoured).
 * @param tenantSlug - The organization's slug.
 * @param projectSlug - The project's slug.
 * @param format - The feed format.
 * @returns `200` with the feed, `304` when unchanged, `404` when the project is not public, or
 *   `503` with `Retry-After` when the database is unavailable.
 */
export async function serveChangelogFeed(
  request: Request,
  tenantSlug: string,
  projectSlug: string,
  format: FeedFormat
): Promise<Response> {
  try {
    const validator = await getFeedValidator(tenantSlug, projectSlug);
    if (!validator) return new Response('Not found', { status: 404 });

    const metaFor = (updated: Date) =>
      buildProjectFeedMeta(
        request.url,
        process.env.NEXT_PUBLIC_BASE_PATH ?? '',
        validator.projectName,
        tenantSlug,
        projectSlug,
        format.extension,
        updated
      );
    const etag = feedValidatorETag(metaFor(new Date(0)).selfUrl, validator);
    const headers = {
      'Content-Type': format.contentType,
      ETag: etag,
      'Cache-Control': 'public, max-age=300',
    };
    if (ifNoneMatchMatches(request.headers.get('if-none-match'), etag)) {
      return new Response(null, { status: 304, headers });
    }

    const rows = await getFeedRows(validator.projectId);
    return new Response(format.render(metaFor(feedUpdatedFromRows(rows)), rows), { headers });
  } catch (err) {
    if (err instanceof DatabaseUnavailableError) return unavailableResponse();
    throw err;
  }
}
