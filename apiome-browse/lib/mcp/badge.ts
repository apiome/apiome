/**
 * Embeddable status-badge helpers — MCAT-19.3 (#4652).
 *
 * Framework-free logic behind the "Status badge" snippet the public MCP endpoint page offers: the
 * badge image URL against the anonymous `/mcp/badge/{tenant}/{slug}.svg` REST surface, the link
 * target (the endpoint's own public detail page), and the ready-to-copy Markdown / HTML / URL
 * snippets an author drops into a README. Kept free of React/DOM so it is unit-testable under the
 * browse Vitest setup (which only runs `lib/**` tests).
 *
 * The badge endpoint lives at the REST origin *root* (`/mcp/badge/...`), not under `/v1`, so
 * {@link badgeOrigin} strips the trailing `/v1` from `NEXT_PUBLIC_REST_API_BASE_URL` before
 * composing the URL.
 */

/** The metrics the badge endpoint can render, in display order. `grade` is the default. */
export const BADGE_METRICS = ['grade', 'health', 'version'] as const;
export type BadgeMetric = (typeof BADGE_METRICS)[number];

/** The label-variant themes the badge endpoint accepts. `light` is the default. */
export const BADGE_THEMES = ['light', 'dark'] as const;
export type BadgeTheme = (typeof BADGE_THEMES)[number];

/** Human labels for the metric selector. */
export const BADGE_METRIC_LABELS: Record<BadgeMetric, string> = {
  grade: 'Grade',
  health: 'Health',
  version: 'Version',
};

/**
 * Reduce the REST API base URL to the origin the badge endpoint is served from.
 *
 * `NEXT_PUBLIC_REST_API_BASE_URL` ends in `/v1` (the versioned API root the rest of the app uses),
 * but the public badge route is mounted at the origin root, so the trailing `/v1` is stripped.
 * Any trailing slashes are trimmed so the composed URL never doubles a separator.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @returns The origin the badge path is appended to (no trailing slash).
 */
export function badgeOrigin(restApiBaseUrl: string): string {
  return restApiBaseUrl.replace(/\/+$/, '').replace(/\/v1$/, '');
}

/**
 * Build the badge image URL for an endpoint, metric, and theme.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @param tenantSlug - The owning tenant's slug.
 * @param endpointSlug - The endpoint's catalog slug.
 * @param metric - Which signal to render (default `grade`).
 * @param theme - The label variant (default `light`).
 * @returns The absolute `.svg` badge URL, with the metric/theme query only when non-default.
 */
export function badgeImageUrl(
  restApiBaseUrl: string,
  tenantSlug: string,
  endpointSlug: string,
  metric: BadgeMetric = 'grade',
  theme: BadgeTheme = 'light'
): string {
  const base = `${badgeOrigin(restApiBaseUrl)}/mcp/badge/${encodeURIComponent(
    tenantSlug
  )}/${encodeURIComponent(endpointSlug)}.svg`;
  const query: string[] = [];
  // Keep the URL clean: only emit params that differ from the endpoint's own defaults.
  if (metric !== 'grade') query.push(`metric=${metric}`);
  if (theme !== 'light') query.push(`theme=${theme}`);
  return query.length ? `${base}?${query.join('&')}` : base;
}

/**
 * Build the badge's link target — the endpoint's public detail page.
 *
 * @param appOrigin - The browse app's own origin (e.g. `https://catalog.example.com`).
 * @param tenantSlug - The owning tenant's slug.
 * @param endpointSlug - The endpoint's catalog slug.
 * @returns The absolute URL of the endpoint's detail page.
 */
export function badgeLinkUrl(appOrigin: string, tenantSlug: string, endpointSlug: string): string {
  return `${appOrigin.replace(/\/+$/, '')}/mcp/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(
    endpointSlug
  )}`;
}

/** The alt / title text for a badge of a given metric and endpoint name. */
export function badgeAltText(endpointName: string, metric: BadgeMetric): string {
  return `${endpointName} MCP ${metric}`;
}

/** The three copyable snippet formats. */
export type BadgeSnippetFormat = 'markdown' | 'html' | 'url';

/**
 * Compose a copyable badge snippet in one of the supported formats.
 *
 * `markdown` and `html` wrap the badge image in a link to the endpoint's detail page (so a reader
 * clicks through to the catalog); `url` is the bare image URL for consumers that only want the SVG.
 *
 * @param format - `markdown`, `html`, or `url`.
 * @param imageUrl - The badge image URL (from {@link badgeImageUrl}).
 * @param linkUrl - The endpoint detail-page URL (from {@link badgeLinkUrl}).
 * @param alt - Alt text describing the badge.
 * @returns The snippet text to place on the clipboard.
 */
export function badgeSnippet(
  format: BadgeSnippetFormat,
  imageUrl: string,
  linkUrl: string,
  alt: string
): string {
  switch (format) {
    case 'markdown':
      return `[![${alt}](${imageUrl})](${linkUrl})`;
    case 'html':
      return `<a href="${linkUrl}"><img src="${imageUrl}" alt="${alt}" /></a>`;
    case 'url':
    default:
      return imageUrl;
  }
}
