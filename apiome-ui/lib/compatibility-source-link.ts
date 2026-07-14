/**
 * Build deep links from compatibility findings to source viewers (CLX-2.3 / #4853).
 */

export type CompatibilitySourceLinkInput = {
  /** OpenAPI entity path or source file path from the finding. */
  path: string;
  /** Optional 1-based line from oasdiff ``revisionSource`` / ``baseSource``. */
  line?: number | null;
  /** Current page search string (without leading ``?``), preserved in the link. */
  currentSearch?: string;
  /** Optional absolute or relative base (defaults to current path query only). */
  pathname?: string;
};

/**
 * Build a relative href that carries ``sourcePath`` + optional ``line`` query params.
 *
 * Catalog Source viewers honor these params to open and highlight the affected location.
 */
export function buildCompatibilitySourceHref(input: CompatibilitySourceLinkInput): string {
  const params = new URLSearchParams(input.currentSearch || '');
  params.set('sourcePath', input.path || '(document)');
  if (typeof input.line === 'number' && input.line > 0) {
    params.set('line', String(input.line));
  } else {
    params.delete('line');
  }
  // Force the catalog detail Source tab when linking into catalog URLs.
  if (!params.get('tab')) {
    params.set('tab', 'source');
  }
  const query = params.toString();
  const base = input.pathname || '';
  return query ? `${base}?${query}` : base || '?';
}

/**
 * Parse ``sourcePath`` / ``line`` from a URLSearchParams-like map.
 */
export function parseCompatibilitySourceQuery(searchParams: {
  get(name: string): string | null;
}): { sourcePath: string | null; line: number | null } {
  const sourcePath = searchParams.get('sourcePath');
  const rawLine = searchParams.get('line');
  let line: number | null = null;
  if (rawLine != null && rawLine.trim() !== '') {
    const n = Number.parseInt(rawLine, 10);
    if (Number.isFinite(n) && n > 0) {
      line = n;
    }
  }
  return { sourcePath: sourcePath && sourcePath.trim() ? sourcePath : null, line };
}
