/**
 * Deep-link anchors into a rendered version page.
 *
 * The version page gives every operation and schema a stable element id (`SpecViewer`), and the
 * search results link straight to them. The id algorithm lives here — framework-free — so the
 * sidebar, the viewer and the search results compute the same string from the same inputs, and a
 * unit test can pin it.
 */

/** The element id of an operation row: `op-get-pets-petid`. */
export function operationAnchorId(method: string, path: string): string {
  const slug = `${method}-${path}`
    .toLowerCase()
    .replace(/[{}]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `op-${slug}`;
}

/** The element id of a schema card: `schema-Pet`. */
export function schemaAnchorId(schemaName: string): string {
  const slug = schemaName.replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '');
  return `schema-${slug || 'unnamed'}`;
}

/**
 * The public URL of a version page, optionally at an anchor and with the find box pre-filled.
 *
 * @param anchor An element id to jump to (`op-…`, `schema-…`).
 * @param find A find-in-version query (BDX-1.3); the page opens already narrowed to it.
 * @returns `/tenant/<t>/<p>/<v>[?find=…][#anchor]`.
 */
export function versionHref(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string,
  anchor?: string | null,
  find?: string | null
): string {
  const base = `/tenant/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(projectSlug)}/${encodeURIComponent(versionSlug)}`;
  const query = find?.trim() ? `?find=${encodeURIComponent(find.trim())}` : '';
  return `${base}${query}${anchor ? `#${anchor}` : ''}`;
}

/**
 * The public URL of a version page opened on its *Changes* tab (the classified changelog).
 *
 * @returns `/tenant/<t>/<p>/<v>?tab=changes`.
 */
export function versionChangesHref(tenantSlug: string, projectSlug: string, versionSlug: string): string {
  return `${versionHref(tenantSlug, projectSlug, versionSlug)}?tab=changes`;
}
