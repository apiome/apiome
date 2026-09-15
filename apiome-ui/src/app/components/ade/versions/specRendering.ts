/**
 * How a version's OpenAPI document is rendered for reading — shared by the Versions screen's spec
 * viewer (HIVE-6.2, #5313) and the review page's Spec tab (COL-2.2, #4518).
 *
 * The document is built as JSON text (`buildOpenApiSpecJsonForVersion`); these helpers only read
 * that text, the chosen rendering and the names, so both surfaces show and name it identically.
 */

import YAML from 'yaml';

/** The two renderings the viewers offer, in tab order. */
export const SPEC_FORMATS = ['json', 'yaml'] as const;

/** One rendering. */
export type SpecFormat = (typeof SPEC_FORMATS)[number];

/**
 * The spec in the chosen rendering.
 *
 * @param spec The JSON text.
 * @param format The rendering.
 * @returns The text to show, copy or download.
 */
export function renderSpec(spec: string, format: SpecFormat): string {
  if (format === 'json') return spec;
  return YAML.stringify(JSON.parse(spec || '{}'));
}

/**
 * The file name a download is saved as — `payments-api-2-3-1-openapi.json`.
 *
 * @param projectSlug The project's slug, or `undefined`.
 * @param versionId The version label, or `undefined`.
 * @param format The rendering.
 * @returns The file name.
 */
export function specDownloadName(
  projectSlug: string | undefined,
  versionId: string | undefined,
  format: SpecFormat
): string {
  const slug = projectSlug || 'api';
  const version = versionId?.replace(/\./g, '-') || '1-0-0';
  return `${slug}-${version}-openapi.${format === 'json' ? 'json' : 'yaml'}`;
}
