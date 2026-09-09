/**
 * Public "Get SDK" helpers — SDK-3.3 (#4493).
 *
 * Framework-free logic behind the browse Get SDK panel: the wire types of the anonymous
 * `/v1/browse/.../sdk` REST surface, the URL builders the panel fetches with, and the
 * presentation helpers (download filename fallback, error copy). Kept free of React/DOM so it is
 * unit-testable under the browse Vitest setup, which only runs `lib/**` tests.
 *
 * The types mirror the REST response models in `apiome-rest/src/app/sdk_kit_routes.py`, so field
 * names are snake_case as they arrive on the wire — the same convention `lib/export/publicExport`
 * follows for the sibling public export surface.
 *
 * **The 404 is the contract.** A project that has not enabled public SDK access answers exactly
 * the same 404 as an unpublished or unknown version. The panel is therefore not a "disabled"
 * state to render — it is a panel that only exists once the info call succeeds.
 */

import { readProblemDetail } from '../http/problemDetail';
import type { PublicExportCoordinates } from '../export/publicExport';

/**
 * The slug coordinates identifying the published version.
 *
 * Re-exported from the public export module rather than redeclared: both anonymous browse
 * surfaces address a version the same way, and two identical interfaces would drift.
 */
export type PublicSdkCoordinates = PublicExportCoordinates;

/** A canonical snippet language, as the REST surface names it. */
export type SdkLang = 'ts' | 'python' | 'curl';

/** One language the kit and the snippet tabs offer. */
export interface PublicSdkLanguage {
  lang: string;
  label: string;
  install?: string | null;
  file_extension: string;
}

/** One resolved package name, as the tenant's SDK-3.4 patterns produce it. */
export interface PublicSdkPackage {
  ecosystem: string;
  name: string;
  install?: string | null;
}

/**
 * The generated Go client the download carries — SDK-2.4 (#4488).
 *
 * Not one of `languages`: those are snippet tabs a reader copies from, while this is a compilable
 * module inside the archive with a path a consumer imports.
 */
export interface PublicSdkGoClient {
  directory: string;
  module_path: string;
  package_name: string;
  go_version: string;
  install?: string | null;
  method_count: number;
}

/** What the download will be, so the button can be labelled before it is fetched. */
export interface PublicSdkDownload {
  filename: string;
  media_type: string;
  schema_version: string;
}

/** The `GET .../sdk` response: everything the panel draws itself from. */
export interface PublicSdkInfoResponse {
  tenant_slug: string;
  project_slug: string;
  version_slug: string;
  version_record_id: string;
  version_label?: string | null;
  api_title?: string | null;
  languages: PublicSdkLanguage[];
  packages: PublicSdkPackage[];
  operation_count: number;
  total_operation_count: number;
  truncated: boolean;
  license_header?: string | null;
  settings_fingerprint?: string | null;
  /** Optional so a panel keeps rendering against a REST build older than SDK-2.4. */
  go_client?: PublicSdkGoClient | null;
  download: PublicSdkDownload;
}

/**
 * Build the base URL of the public SDK surface for one published version.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`
 *   (`NEXT_PUBLIC_REST_API_BASE_URL`), exactly as `SpecViewer` uses it.
 * @param coords - The tenant/project/version slugs of the viewed published version.
 * @returns The `.../sdk` base the `/download` path appends to.
 */
function publicSdkBaseUrl(restApiBaseUrl: string, coords: PublicSdkCoordinates): string {
  const tenant = encodeURIComponent(coords.tenantSlug);
  const project = encodeURIComponent(coords.projectSlug);
  const version = encodeURIComponent(coords.versionSlug);
  return `${restApiBaseUrl}/browse/tenants/${tenant}/projects/${project}/versions/${version}/sdk`;
}

/**
 * The URL describing the SDK on offer for one published version.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @param coords - The tenant/project/version slugs of the viewed published version.
 * @returns The absolute `GET .../sdk` URL.
 */
export function publicSdkInfoUrl(
  restApiBaseUrl: string,
  coords: PublicSdkCoordinates
): string {
  return publicSdkBaseUrl(restApiBaseUrl, coords);
}

/**
 * The URL serving the client-kit archive for one published version.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @param coords - The tenant/project/version slugs of the viewed published version.
 * @returns The absolute `GET .../sdk/download` URL.
 */
export function publicSdkDownloadUrl(
  restApiBaseUrl: string,
  coords: PublicSdkCoordinates
): string {
  return `${publicSdkBaseUrl(restApiBaseUrl, coords)}/download`;
}

/**
 * The fallback download filename when the response names none.
 *
 * Mirrors the REST layer's own naming (`widgets-1.0.0-sdk.zip`) and the export dialog's fallback
 * shape, so a saved file is recognisable however it was named.
 *
 * @param coords - The version's slug coordinates.
 * @returns A stable, human-readable filename.
 */
export function sdkFallbackFilename(coords: PublicSdkCoordinates): string {
  return `${coords.projectSlug}-${coords.versionSlug}-sdk.zip`;
}

/**
 * Whether an info response has any package name to show.
 *
 * A tenant that has configured no package patterns still gets a kit — the snippets are the point —
 * so the panel's package block is conditional rather than always-present-and-empty.
 *
 * @param info - The info response.
 * @returns True when at least one ecosystem resolved to a name.
 */
export function hasPackages(info: PublicSdkInfoResponse): boolean {
  return info.packages.length > 0;
}

/**
 * The sentence describing how much of the API the kit covers.
 *
 * @param info - The info response.
 * @returns A short sentence for the panel, naming the truncation when there is one.
 */
export function coverageSummary(info: PublicSdkInfoResponse): string {
  const { operation_count: covered, total_operation_count: total, truncated } = info;
  const noun = covered === 1 ? 'operation' : 'operations';
  if (truncated) {
    return `Runnable examples for the first ${covered} of ${total} operations.`;
  }
  if (covered === total) {
    return `Runnable examples for all ${covered} ${noun}.`;
  }
  return `Runnable examples for ${covered} of ${total} operations.`;
}

/**
 * A stable, user-facing message for a failed SDK download.
 *
 * The info call needs none of this — a failure there means the panel is simply not rendered — but
 * a download that fails after the user clicked has to say something.
 *
 * @param status - The HTTP status code from fetch.
 * @param detail - The server's `detail` sentence, when it sent one.
 * @returns A short sentence suitable for the panel's error line.
 */
export function publicSdkErrorMessage(status: number, detail?: string | null): string {
  if (status === 429) {
    return (
      detail ?? 'Too many requests from this browser. Please wait a moment and try again.'
    );
  }
  if (status === 413) {
    return (
      detail ?? 'This SDK is too large to download publicly. Contact the publisher for a copy.'
    );
  }
  if (status === 404) {
    return detail ?? 'This SDK is no longer available for download.';
  }
  return detail ?? `Download failed (${status}).`;
}

/**
 * Read a non-OK SDK response once and build its error message.
 *
 * @param response - A non-OK fetch Response from the public SDK surface.
 * @returns The message to show.
 */
export async function publicSdkErrorFromResponse(response: Response): Promise<string> {
  const detail = await readProblemDetail(response);
  return publicSdkErrorMessage(response.status, detail);
}
