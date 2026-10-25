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

/** The public URL of a version page, optionally at an anchor. */
export function versionHref(
  tenantSlug: string,
  projectSlug: string,
  versionSlug: string,
  anchor?: string | null
): string {
  const base = `/tenant/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(projectSlug)}/${encodeURIComponent(versionSlug)}`;
  return anchor ? `${base}#${anchor}` : base;
}
