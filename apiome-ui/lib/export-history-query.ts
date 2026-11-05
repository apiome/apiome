/**
 * The export history's query string, allow-listed for REST (MFX-46.1, #4379).
 *
 * `GET /api/export/runs` forwards only the filters `GET /v1/export/{tenant}/runs` accepts; anything else
 * in the browser's query string is dropped, never passed on.
 */

/** The history filters REST accepts. */
export const EXPORT_RUN_FILTERS = [
  'artifact',
  'target',
  'actor',
  'state',
  'channel',
  'validation',
  'decision',
  'finished_after',
  'finished_before',
  'limit',
  'offset',
] as const;

/**
 * The allow-listed query string for REST.
 *
 * @param params The incoming search parameters.
 * @returns `?a=b…`, or an empty string with no filter.
 */
export function exportRunQuery(params: Pick<URLSearchParams, 'get'>): string {
  const query = new URLSearchParams();
  for (const key of EXPORT_RUN_FILTERS) {
    const value = params.get(key);
    if (value !== null && value !== '') query.set(key, value);
  }
  const text = query.toString();
  return text ? `?${text}` : '';
}
