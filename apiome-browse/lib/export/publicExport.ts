/**
 * Public export helpers — MFX-7.1 (#3860).
 *
 * Framework-free logic behind the public "Export to another format" dialog: the wire types of
 * the anonymous `/v1/browse/.../export/*` REST surface, the URL builders the dialog fetches
 * with, and the pure presentation helpers (tier labels/badges, the fidelity warning, download
 * filenames). Kept free of React/DOM so it is unit-testable under the browse Vitest setup,
 * which only runs `lib/**` tests.
 *
 * The types mirror the REST response models in `apiome-rest/src/app/browse_export_routes.py`
 * (which themselves reuse the authenticated `/v1/export` models), so field names are snake_case
 * as they arrive on the wire.
 */

/** The one-word fidelity badge for exporting the viewed source to one target. */
export type ExportFidelityTier = 'lossless' | 'lossy' | 'types-only';

/** One export target's self-description (key, format, label...), as the registry publishes it. */
export interface ExportTargetDescriptor {
  key: string;
  format: string;
  label: string;
  description: string;
  icon: string;
  paradigm: string;
  multi_file: boolean;
  needs_toolchain: boolean;
  available: boolean;
  unavailable_reason?: string | null;
}

/** The cheap per-target fidelity summary: tier badge, preserved-%, and per-kind counts. */
export interface TargetFidelitySummary {
  tier: ExportFidelityTier;
  preserved_percent: number;
  total: number;
  preserved: number;
  dropped: number;
  approximated: number;
  synthesized: number;
}

/** One entry of the public targets list: descriptor + options + its fidelity badge. */
export interface PublicExportTarget {
  descriptor: ExportTargetDescriptor;
  capability_profile: Record<string, boolean>;
  options_schema: Record<string, unknown>;
  default_options: Record<string, unknown>;
  fidelity: TargetFidelitySummary;
}

/** The `GET .../export/targets` response: slug coordinates + every target with its badge. */
export interface PublicExportTargetsResponse {
  tenant_slug: string;
  project_slug: string;
  version_slug: string;
  version_record_id: string;
  version_label?: string | null;
  targets: PublicExportTarget[];
}

/** The slug coordinates identifying the published version being exported. */
export interface PublicExportCoordinates {
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
}

/** The download serialization the user picked in the dialog. */
export type ExportSerialization = 'json' | 'yaml';

/**
 * Build the base URL of the public export surface for one published version.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`
 *   (`NEXT_PUBLIC_REST_API_BASE_URL`), exactly as `SpecViewer` uses it.
 * @param coords - The tenant/project/version slugs of the viewed published version.
 * @returns The `.../export` base the `/targets` and `/document` paths append to.
 */
function publicExportBaseUrl(restApiBaseUrl: string, coords: PublicExportCoordinates): string {
  const tenant = encodeURIComponent(coords.tenantSlug);
  const project = encodeURIComponent(coords.projectSlug);
  const version = encodeURIComponent(coords.versionSlug);
  return `${restApiBaseUrl}/browse/tenants/${tenant}/projects/${project}/versions/${version}/export`;
}

/**
 * The URL listing every export target (with fidelity badges) for one published version.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @param coords - The tenant/project/version slugs of the viewed published version.
 * @returns The absolute `GET .../export/targets` URL.
 */
export function publicExportTargetsUrl(
  restApiBaseUrl: string,
  coords: PublicExportCoordinates
): string {
  return `${publicExportBaseUrl(restApiBaseUrl, coords)}/targets`;
}

/**
 * The URL emitting the export document for one published version.
 *
 * @param restApiBaseUrl - The browser-reachable REST base URL, ending in `/v1`.
 * @param coords - The tenant/project/version slugs of the viewed published version.
 * @returns The absolute `POST .../export/document` URL.
 */
export function publicExportDocumentUrl(
  restApiBaseUrl: string,
  coords: PublicExportCoordinates
): string {
  return `${publicExportBaseUrl(restApiBaseUrl, coords)}/document`;
}

/**
 * The `Accept` header value selecting the chosen download serialization.
 *
 * @param serialization - The serialization the user picked (`json` or `yaml`).
 * @returns The header value the document endpoint content-negotiates on.
 */
export function serializationAcceptHeader(serialization: ExportSerialization): string {
  return serialization === 'yaml' ? 'application/yaml' : 'application/json';
}

/** Rank used to sort targets best-fidelity-first in the dialog's card grid. */
const TIER_RANK: Record<ExportFidelityTier, number> = {
  lossless: 0,
  lossy: 1,
  'types-only': 2,
};

/**
 * Order the targets for the dialog's card grid: available targets first, then by fidelity
 * (lossless before lossy before types-only), then by preserved-% (descending), then label.
 *
 * @param targets - The targets as the REST surface returned them (registry order).
 * @returns A new sorted array; the input is not mutated.
 */
export function sortTargetsForDisplay(targets: PublicExportTarget[]): PublicExportTarget[] {
  return [...targets].sort((a, b) => {
    if (a.descriptor.available !== b.descriptor.available) {
      return a.descriptor.available ? -1 : 1;
    }
    const tierDelta = TIER_RANK[a.fidelity.tier] - TIER_RANK[b.fidelity.tier];
    if (tierDelta !== 0) return tierDelta;
    const preservedDelta = b.fidelity.preserved_percent - a.fidelity.preserved_percent;
    if (preservedDelta !== 0) return preservedDelta;
    return a.descriptor.label.localeCompare(b.descriptor.label);
  });
}

/**
 * The human label of a fidelity tier, matching the ADE's wording.
 *
 * @param tier - The tier badge from the targets response.
 * @returns The short label rendered on the target card's badge.
 */
export function tierLabel(tier: ExportFidelityTier): string {
  switch (tier) {
    case 'lossless':
      return 'Full fidelity';
    case 'lossy':
      return 'May lose fidelity';
    case 'types-only':
      return 'Types only';
  }
}

/**
 * The Tailwind classes of a tier badge, in browse's zinc/emerald/amber/rose palette.
 *
 * @param tier - The tier badge from the targets response.
 * @returns The class string for the badge `span` (light + dark variants).
 */
export function tierBadgeClass(tier: ExportFidelityTier): string {
  switch (tier) {
    case 'lossless':
      return 'bg-emerald-50 text-emerald-700 ring-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-500/30';
    case 'lossy':
      return 'bg-amber-50 text-amber-700 ring-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30';
    case 'types-only':
      return 'bg-rose-50 text-rose-700 ring-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-500/30';
  }
}

/**
 * Whether exporting at this tier requires the explicit "Export anyway" acknowledgement.
 *
 * Mirrors the ADE's gate: anything short of lossless must be acknowledged before the
 * export button enables.
 *
 * @param tier - The selected target's tier badge.
 * @returns True when the acknowledgement checkbox gates the export.
 */
export function requiresExportAcknowledgement(tier: ExportFidelityTier): boolean {
  return tier !== 'lossless';
}

/**
 * The fidelity warning sentence for a lossy/types-only target, built from the badge counts.
 *
 * (The full per-construct advisory report arrives with MFX-7.2; this is the headline warning
 * MFX-7.1's acceptance criteria require.)
 *
 * @param target - The selected target entry.
 * @returns The warning sentence, or an empty string for a lossless target.
 */
export function fidelityWarningMessage(target: PublicExportTarget): string {
  const { tier, total, dropped, approximated, synthesized, preserved_percent } = target.fidelity;
  if (!requiresExportAcknowledgement(tier)) return '';
  const losses: string[] = [];
  if (dropped > 0) losses.push(`${dropped} dropped`);
  if (approximated > 0) losses.push(`${approximated} approximated`);
  if (synthesized > 0) losses.push(`${synthesized} synthesized`);
  const detail = losses.length > 0 ? ` (${losses.join(', ')})` : '';
  const scope =
    tier === 'types-only'
      ? 'keeps only the type definitions — operations are not carried over'
      : 'may lose fidelity';
  return (
    `Exporting to ${target.descriptor.label} ${scope}: ` +
    `${preserved_percent}% of ${total} source constructs are preserved${detail}.`
  );
}

/**
 * Extract the download filename from a `Content-Disposition` header.
 *
 * @param header - The header value (e.g. `attachment; filename="asyncapi.yaml"`), or null.
 * @param fallback - The name used when the header is missing or carries no filename.
 * @returns The filename to save the exported document as.
 */
export function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const match = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  const name = match?.[1]?.trim();
  return name || fallback;
}

/**
 * The fallback download filename when the response names none.
 *
 * @param coords - The exported version's slug coordinates.
 * @param targetKey - The chosen target's registry key (e.g. `asyncapi`).
 * @param serialization - The chosen serialization (drives the extension).
 * @returns A stable, human-readable filename like `widgets-1.0.0-asyncapi.yaml`.
 */
export function exportFallbackFilename(
  coords: PublicExportCoordinates,
  targetKey: string,
  serialization: ExportSerialization
): string {
  return `${coords.projectSlug}-${coords.versionSlug}-${targetKey}.${serialization}`;
}
