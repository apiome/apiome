/**
 * Stored overlay chain transport and model — GVM-4.3 (#5878).
 *
 * Thin `fetch` wrappers over `/api/versions/{v}/overlays*`, which forward to apiome-rest for the
 * session's tenant. Every function resolves with parsed data or throws a
 * {@link VersionOverlaysError} carrying the REST message, status and refusal code.
 */

import type { ExportOverlayFinding, ExportOverlayReport } from '../dashboard/export/exportOverlays';

/** Where a stored overlay came from (REST `VersionOverlayWrite.source`). */
export type OverlaySource = 'manual' | 'lint-fix' | 'export-studio' | 'enrichment-export';

/** Readable labels for {@link OverlaySource}. */
export const OVERLAY_SOURCE_LABEL: Record<OverlaySource, string> = {
  manual: 'Uploaded',
  'lint-fix': 'Lint fix',
  'export-studio': 'Export Studio',
  'enrichment-export': 'Agent enrichment',
};

/** A revision row as `/api/versions?projectId=…` lists it (the fields the overlay surfaces read). */
export interface VersionOverlaysRevisionRow {
  id: string;
  project_id: string;
  version_id: string;
  published: boolean;
  deleted_at?: string | null;
}

/** The refusal code for a write on a published revision. */
export const CODE_VERSION_PUBLISHED = 'overlay-version-published';

/** One stored overlay (REST `VersionOverlayOut`). */
export interface StoredVersionOverlay {
  id: string;
  position: number;
  name: string;
  source: OverlaySource;
  content_fingerprint: string;
  action_count: number;
  created_by: string | null;
  created_at: string | null;
  document: Record<string, unknown>;
}

/** The publish render record (REST `VersionOverlayRenderOut`). */
export interface VersionOverlayRender {
  source_fingerprint: string;
  resolved_fingerprint: string;
  overlays: Array<{ id: string; name: string; position: number; contentFingerprint: string }>;
  findings: ExportOverlayFinding[];
  changes: number;
  rendered_by: string | null;
  rendered_at: string | null;
}

/** A revision's chain (REST `VersionOverlayChainOut`). */
export interface VersionOverlayChain {
  version_record_id: string;
  published: boolean;
  max_overlays: number;
  overlays: StoredVersionOverlay[];
  render: VersionOverlayRender | null;
}

/** The chain preview (REST `VersionOverlayPreviewOut`). */
export interface VersionOverlayPreview {
  version_record_id: string;
  source_fingerprint: string;
  resolved_fingerprint: string;
  document: Record<string, unknown>;
  report: ExportOverlayReport | null;
}

/** The body of an add or replace. */
export interface VersionOverlayWrite {
  name: string;
  source: OverlaySource;
  document: Record<string, unknown>;
  position?: number;
}

/** A refused or failed overlay call. */
export class VersionOverlaysError extends Error {
  /** The HTTP status (0 when the request never got an answer). */
  readonly status: number;

  /** apiome-rest's refusal code, e.g. `overlay-version-published`. */
  readonly code: string | null;

  /**
   * @param message What went wrong, fit to show.
   * @param status The HTTP status.
   * @param code The refusal code, when there is one.
   */
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'VersionOverlaysError';
    this.status = status;
    this.code = code;
  }
}

/**
 * The BFF URL of a revision's chain (or a path under it).
 *
 * @param projectId The revision's project.
 * @param versionId The revision.
 * @param suffix `''`, `'/preview'` or `'/<id>'`.
 */
export function overlaysUrl(projectId: string, versionId: string, suffix = ''): string {
  return `/api/versions/${encodeURIComponent(versionId)}/overlays${suffix}?projectId=${encodeURIComponent(projectId)}`;
}

/**
 * Call one overlay route and unwrap `{success, data}`.
 *
 * @param url The BFF URL.
 * @param init `method` and JSON `body`.
 * @returns The `data` of a successful reply.
 * @throws VersionOverlaysError on a refusal or an unreadable reply.
 */
async function call(url: string, init: { method?: string; body?: unknown } = {}): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: init.method ?? 'GET',
      credentials: 'include',
      headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new VersionOverlaysError('Apiome could not be reached.', 0);
  }
  let payload: { success?: boolean; data?: unknown; error?: unknown; code?: unknown } = {};
  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    payload = {};
  }
  if (payload.success !== true) {
    throw new VersionOverlaysError(
      typeof payload.error === 'string' && payload.error ? payload.error : 'Request failed',
      response.status,
      typeof payload.code === 'string' ? payload.code : null
    );
  }
  return payload.data;
}

/** List a revision's chain. */
export async function fetchVersionOverlays(projectId: string, versionId: string): Promise<VersionOverlayChain> {
  return (await call(overlaysUrl(projectId, versionId))) as VersionOverlayChain;
}

/** Render a revision's chain the way an export does. */
export async function fetchVersionOverlayPreview(
  projectId: string,
  versionId: string
): Promise<VersionOverlayPreview> {
  return (await call(overlaysUrl(projectId, versionId, '/preview'))) as VersionOverlayPreview;
}

/** Add an overlay to a draft revision's chain. */
export async function addVersionOverlay(
  projectId: string,
  versionId: string,
  body: VersionOverlayWrite
): Promise<StoredVersionOverlay> {
  return (await call(overlaysUrl(projectId, versionId), { method: 'POST', body })) as StoredVersionOverlay;
}

/** Remove an overlay from a draft revision's chain. */
export async function removeVersionOverlay(projectId: string, versionId: string, overlayId: string): Promise<void> {
  await call(overlaysUrl(projectId, versionId, `/${encodeURIComponent(overlayId)}`), { method: 'DELETE' });
}

/**
 * A short form of a `sha256:` fingerprint for a table cell.
 *
 * @param fingerprint `sha256:<hex>`.
 * @returns `sha256:` plus the first 12 hex digits, or the input when it is not a fingerprint.
 */
export function shortFingerprint(fingerprint: string | null | undefined): string {
  if (!fingerprint) return '—';
  const [scheme, hex] = fingerprint.split(':');
  return hex ? `${scheme}:${hex.slice(0, 12)}` : fingerprint;
}

/**
 * Whether a string is a revision UUID (the overlay routes address revisions by id, not label).
 *
 * @param value A version reference.
 */
export function isRevisionId(value: string | null | undefined): value is string {
  return !!value && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
