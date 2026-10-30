/**
 * The rules behind a catalog item's **Uploaded file** card, its stale banner and the **Re-upload**
 * dialog — RAR-6.2 (#3539).
 *
 * An item imported from an uploaded file has no live source to refresh. REST
 * (`/v1/catalog/{slug}/{item}/upload`) says whether the item's newest version came from an upload,
 * how old it is, whether that is past the workspace's threshold (90 days by default), and which
 * import settings the upload recorded. A re-upload (`…/reupload`) replays those settings over the
 * new file. This module turns those answers into what the page prints, and a picked file into the
 * request body, so the components stay thin and the rules testable.
 */

/** The import spec an upload recorded, replayed by a re-upload. */
export interface CatalogUploadSpec {
  specSchemaVersion: number;
  /** The importer the upload ran, e.g. `asyncapi-2`. */
  sourceKind: string;
  /** The import options the user chose (snake_case, as REST stores them). */
  options: Record<string, unknown>;
}

/** `GET /api/catalog/{id}/upload` — the item's upload state. */
export interface CatalogUpload {
  itemId: string;
  /** True when the newest version came from a file upload, so it can be re-uploaded. */
  eligible: boolean;
  /** True when it is eligible and at least `staleAfterDays` old. */
  stale: boolean;
  staleAfterDays: number;
  uploadedAt: string | null;
  ageDays: number | null;
  versionId: string | null;
  versionLabel: string | null;
  /** The uploaded file's name. */
  sourceLabel: string | null;
  /** The stored spec; null for an upload from before spec capture (re-upload uses defaults). */
  spec: CatalogUploadSpec | null;
}

/** `POST /api/catalog/{id}/reupload` — what a re-upload did. */
export interface CatalogReuploadResult {
  status: 'changed' | 'unchanged';
  specReplayed: boolean;
  versionId: string | null;
  versionLabel: string | null;
  /** The item's upload state afterwards. */
  upload: CatalogUpload;
}

/** The body `POST /api/catalog/{id}/reupload` takes. */
export interface CatalogReuploadBody {
  filename: string;
  documentBase64: string;
  contentType?: string;
}

/**
 * How long ago the file was uploaded, in words.
 *
 * @param ageDays Whole days since the upload, or null when unknown.
 * @returns e.g. "today", "1 day ago", "120 days ago", or "at an unknown time".
 */
export function uploadAgeText(ageDays: number | null): string {
  if (ageDays === null || ageDays === undefined) return 'at an unknown time';
  if (ageDays <= 0) return 'today';
  return ageDays === 1 ? '1 day ago' : `${ageDays} days ago`;
}

/**
 * The card's status pill.
 *
 * @param upload The item's upload state.
 * @returns The pill's label and Badge tone.
 */
export function uploadStatusView(upload: CatalogUpload): { label: string; tone: 'warn' | 'ok' } {
  return upload.stale ? { label: 'May be stale', tone: 'warn' } : { label: 'Recent', tone: 'ok' };
}

/**
 * The stale banner's headline.
 *
 * @param upload The item's upload state (stale).
 * @returns e.g. "orders.yaml was uploaded 120 days ago".
 */
export function staleUploadTitle(upload: CatalogUpload): string {
  const name = upload.sourceLabel || 'This file';
  return `${name} was uploaded ${uploadAgeText(upload.ageDays)}`;
}

/** Import-option keys a reader cares about, in the order they print, with their labels. */
const OPTION_LABELS: ReadonlyArray<[string, string]> = [
  ['selected_schemas', 'Schemas'],
  ['apply_naming_convention', 'Apply naming convention'],
  ['class_naming_convention', 'Class names'],
  ['property_naming_convention', 'Property names'],
  ['create_relationships', 'Create relationships'],
  ['auto_layout', 'Auto layout'],
  ['incremental_mode', 'Incremental'],
  ['import_target', 'Import as'],
  ['archive_root', 'Archive root'],
  ['resolve_remote_refs', 'Resolve remote references'],
  ['har_hosts', 'HAR hosts'],
  ['har_include', 'HAR include'],
  ['har_exclude', 'HAR exclude'],
  ['har_keep_noise', 'Keep HAR noise'],
];

/**
 * Print one option value.
 *
 * @param value The stored value.
 * @returns The text, or null when it is unset (false, empty or missing).
 */
function optionValueText(value: unknown): string | null {
  if (value === null || value === undefined || value === false || value === '') return null;
  if (value === true) return 'Yes';
  if (Array.isArray(value)) return value.length ? value.map(String).join(', ') : null;
  if (typeof value === 'object') return Object.keys(value as object).length ? JSON.stringify(value) : null;
  return String(value);
}

/**
 * The import settings a re-upload replays, as label/value rows. Unset options are left out, so an
 * upload that took every default replays "Default settings".
 *
 * @param spec The stored spec, or null for an upload from before spec capture.
 * @returns The rows to print, in a stable order (known options first, then any others by key).
 */
export function replayedSettings(spec: CatalogUploadSpec | null): Array<{ label: string; value: string }> {
  if (!spec) return [];
  const rows: Array<{ label: string; value: string }> = [];
  const known = new Set(OPTION_LABELS.map(([key]) => key));
  for (const [key, label] of OPTION_LABELS) {
    const text = optionValueText(spec.options[key]);
    if (text !== null) rows.push({ label, value: text });
  }
  for (const key of Object.keys(spec.options).sort()) {
    if (known.has(key)) continue;
    const text = optionValueText(spec.options[key]);
    if (text !== null) rows.push({ label: key, value: text });
  }
  return rows;
}

/**
 * What the re-upload replays, in one sentence for the dialog.
 *
 * @param upload The item's upload state.
 * @returns The sentence.
 */
export function replaySummary(upload: CatalogUpload): string {
  if (!upload.spec) {
    return 'This file was uploaded before Apiome kept import settings, so the new file is imported with the default settings.';
  }
  const count = replayedSettings(upload.spec).length;
  if (count === 0) return 'The new file is imported with the same settings as the first upload: the defaults.';
  return count === 1
    ? 'The new file is imported with the 1 setting the first upload used.'
    : `The new file is imported with the ${count} settings the first upload used.`;
}

/**
 * What to tell the user after a re-upload.
 *
 * @param result REST's answer.
 * @returns The message.
 */
export function reuploadResultText(result: CatalogReuploadResult): string {
  if (result.status === 'unchanged') return 'The file matches the current version, so nothing changed.';
  return result.versionLabel ? `Added version ${result.versionLabel}.` : 'Added a new version.';
}

/**
 * Encode bytes as standard base64 (RFC 4648), the form REST expects.
 *
 * @param bytes The file's bytes.
 * @returns The base64 text.
 */
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

/**
 * Read a picked file into the re-upload body.
 *
 * @param file The file from the dialog's file input.
 * @returns The body to POST.
 */
export async function reuploadBodyFrom(file: File): Promise<CatalogReuploadBody> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  return {
    filename: file.name,
    documentBase64: bytesToBase64(bytes),
    ...(file.type ? { contentType: file.type } : {}),
  };
}

/**
 * Read a JSON answer through the BFF, throwing its error message on failure.
 *
 * @param url The BFF URL.
 * @param fallback The message when the answer carries none.
 * @param init The fetch options.
 * @returns The parsed JSON.
 */
export async function requestUploadJson<T>(url: string, fallback: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    throw new Error(data?.error || fallback);
  }
  return data as T;
}
