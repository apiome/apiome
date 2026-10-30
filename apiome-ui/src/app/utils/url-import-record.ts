/**
 * Record a URL import for auto-refresh (RAR-6.1, #3538).
 *
 * After an import from the **URL Import** source succeeds, the import dialog tells REST where the
 * spec came from (`POST /api/url-imports`), so REST re-checks the URL on the refresh cadence and
 * adds a version when the document changes. The options sent are the ones the import used, so a
 * refresh replays them. A URL fetched with credentials is recorded as `authenticated`: REST never
 * refreshes it, and no credential is ever sent.
 */

/** Where a URL import's document came from (set by the URL Import panel). */
export interface UrlImportSource {
  /** The URL the document was fetched from. */
  url: string;
  /** True when the fetch used Basic, Bearer or API-key auth. */
  authenticated: boolean;
  /** The response's `Content-Type`, when the server sent one. */
  contentType?: string | null;
}

/** The `POST /api/url-imports` body. */
export interface UrlImportRecordBody {
  projectId: string;
  versionId?: string;
  url: string;
  sourceKind: string;
  contentType?: string | null;
  options: Record<string, unknown>;
  authenticated: boolean;
}

/**
 * Build the record body for a finished import, or `null` when there is nothing to record.
 *
 * @param source Where the document came from; `null` for any other import source.
 * @param result The finished import's result (`projectId`, `versionId`).
 * @param sourceKind The importer kind the import used (`openapi`, `arazzo`).
 * @param options The import options the import used; `dryRun` is dropped.
 * @returns The body, or `null` without a source or a project.
 */
export function buildUrlImportRecord(
  source: UrlImportSource | null,
  result: { projectId?: string | null; versionId?: string | null } | null | undefined,
  sourceKind: string,
  options: Record<string, unknown>,
): UrlImportRecordBody | null {
  const url = source?.url?.trim();
  const projectId = result?.projectId?.trim();
  if (!source || !url || !projectId) return null;
  const replayed = Object.fromEntries(Object.entries(options).filter(([key]) => key !== 'dryRun'));
  return {
    projectId,
    ...(result?.versionId ? { versionId: result.versionId } : {}),
    url,
    sourceKind,
    contentType: source.contentType ?? null,
    options: replayed,
    authenticated: source.authenticated,
  };
}

/**
 * Send the record. Best-effort: a failure is logged and reported, never thrown, because the import
 * itself already succeeded.
 *
 * @param body From {@link buildUrlImportRecord}.
 * @param fetchImpl The fetch to use (tests pass one).
 * @returns `true` when REST recorded it.
 */
export async function recordUrlImport(
  body: UrlImportRecordBody,
  fetchImpl: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const response = await fetchImpl('/api/url-imports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) console.warn('[url-import] could not record the URL for refresh', response.status);
    return response.ok;
  } catch (error) {
    console.warn('[url-import] could not record the URL for refresh', error instanceof Error ? error.name : 'unknown');
    return false;
  }
}
